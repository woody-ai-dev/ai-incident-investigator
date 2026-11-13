from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_incident_investigator.investigations.reports import (
    CollectionStatus,
    EvidenceSource,
    SourceCollection,
)
from ai_incident_investigator.knowledge.applicability import applicable_hits
from ai_incident_investigator.knowledge.documents import KnowledgeMetadata
from ai_incident_investigator.knowledge.extraction import LocalDocumentExtractor
from ai_incident_investigator.knowledge.recommendations import InvestigationExport
from ai_incident_investigator.knowledge.retrieval_chunks import prepare_document_chunks
from ai_incident_investigator.knowledge.vector_index import SearchHit

EXPORTS = Path(__file__).resolve().parents[1] / "evals/fixtures/knowledge-recommendations"
PAYMENT_LOG_RULE = {"kind": "log_prefix", "prefix": "Payment request timed out"}
HEAP_METRIC_RULE = {"kind": "metric", "evidence_id": "metric-jvm-heap"}
COLLECTION_GAP_RULE = {"kind": "collection_gap"}


def load_export(case_id: str) -> InvestigationExport:
    return InvestigationExport.model_validate_json((EXPORTS / f"{case_id}.json").read_bytes())


def make_hit(document_id: str, *rules: dict[str, str], reference_only: bool = False) -> SearchHit:
    metadata = KnowledgeMetadata.model_validate(
        {
            "id": document_id,
            "title": "Example investigation",
            "document_type": "runbook",
            "file": f"knowledge/{document_id}.md",
            "service": "order-service",
            "environment": "local",
            "owner": "fixture-owner",
            "version": 1,
            "status": "approved",
            "reviewed_by": "fixture-reviewer",
            **({"applicability": rules} if rules or reference_only else {}),
        }
    )
    document = LocalDocumentExtractor().extract(metadata, b"Review retained diagnostic records.")
    (chunk,) = prepare_document_chunks(document)
    return SearchHit(chunk=chunk, score=0.9)


@pytest.mark.parametrize(
    ("case_id", "eligible"),
    [
        ("simulated-payment-timeout", True),
        ("scrape-and-late-health", True),
        ("same-scope-tls-expiry", False),
    ],
)
def test_runbook_applies_to_recorded_timeout_not_same_service_alone(
    case_id: str, eligible: bool
) -> None:
    # No registered heap metric exists here. The timeout signal is sufficient by itself.
    hit = make_hit("example-runbook", HEAP_METRIC_RULE, PAYMENT_LOG_RULE)
    assert applicable_hits(load_export(case_id), (hit,)) == ((hit,) if eligible else ())


@pytest.mark.parametrize(
    ("source", "summary", "at_window_end", "eligible"),
    [
        (EvidenceSource.LOG, "Payment request timed out", False, True),
        (EvidenceSource.LOG, "[WARN] Did not observe: Payment request timed out", False, False),
        (EvidenceSource.TRACE, "Payment request timed out", False, False),
        (EvidenceSource.LOG, "Payment request timed out", True, False),
    ],
)
def test_log_signal_requires_matching_prefix_source_and_window(
    source: EvidenceSource, summary: str, at_window_end: bool, eligible: bool
) -> None:
    investigation = load_export("simulated-payment-timeout")
    event = investigation.report.evidence[0]
    event.source = source
    event.summary = summary
    if at_window_end:
        event.start_time = investigation.request.end_time

    hit = make_hit("example-runbook", PAYMENT_LOG_RULE)
    assert applicable_hits(investigation, (hit,)) == ((hit,) if eligible else ())


def test_request_and_prior_analysis_are_not_telemetry() -> None:
    investigation = load_export("same-scope-tls-expiry")
    text = "Payment request timed out"
    investigation.request.description = text
    investigation.report.summary = text
    investigation.report.missing_data.append(text)

    hit = make_hit("example-runbook", PAYMENT_LOG_RULE)
    assert applicable_hits(investigation, (hit,)) == ()


@pytest.mark.parametrize("source", [EvidenceSource.METRIC, EvidenceSource.LOG])
def test_registered_metric_signal_matches_overlapping_metric_only(source: EvidenceSource) -> None:
    investigation = load_export("scrape-and-late-health")
    metric = investigation.report.evidence[1]
    metric.id = "metric-jvm-heap"
    metric.summary = "Aggregated JVM heap usage in bytes"
    metric.source = source
    metric.start_time = investigation.request.start_time.replace(hour=9)

    hit = make_hit("heap-guide", HEAP_METRIC_RULE)
    assert applicable_hits(investigation, (hit,)) == (
        (hit,) if source == EvidenceSource.METRIC else ()
    )


def test_unknown_metric_is_rejected_at_metadata_validation() -> None:
    with pytest.raises(ValidationError):
        make_hit("unknown-guide", {"kind": "metric", "evidence_id": "metric-unknown"})


@pytest.mark.parametrize(
    ("status", "eligible"),
    [(None, False), (CollectionStatus.COLLECTED, False), (CollectionStatus.PARTIAL, True)],
)
def test_collection_gap_needs_a_structured_collection_outcome(
    status: CollectionStatus | None, eligible: bool
) -> None:
    investigation = load_export("same-scope-tls-expiry")
    if status is not None:
        issues = ["Log coverage is incomplete."] if status == CollectionStatus.PARTIAL else []
        investigation.report.source_collections = [
            SourceCollection(
                source=EvidenceSource.LOG,
                status=status,
                evidence_count=1,
                duration_ms=1,
                issues=issues,
            )
        ]

    hit = make_hit("collection-guide", COLLECTION_GAP_RULE)
    assert applicable_hits(investigation, (hit,)) == ((hit,) if eligible else ())


def test_filter_keeps_legacy_documents_and_preserves_survivor_order() -> None:
    investigation = load_export("simulated-payment-timeout")
    legacy = make_hit("legacy-guide")
    reference = make_hit("reference-guide", reference_only=True)
    unrelated = make_hit("heap-guide", HEAP_METRIC_RULE)
    relevant = make_hit("example-runbook", PAYMENT_LOG_RULE)

    assert applicable_hits(investigation, (legacy, reference, unrelated, relevant)) == (
        legacy,
        relevant,
    )
