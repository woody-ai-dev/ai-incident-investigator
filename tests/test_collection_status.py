import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

import ai_incident_investigator.sources.collection as collection_module
from ai_incident_investigator.investigations.reports import (
    CollectionStatus,
    EvidenceSource,
    InvestigationReport,
    SourceCollection,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate
from ai_incident_investigator.settings import ActuatorTarget
from ai_incident_investigator.sources.actuator import HttpActuatorCollector
from ai_incident_investigator.sources.collection import CollectionResult, collect_source
from ai_incident_investigator.sources.logs import collect_logs
from ai_incident_investigator.sources.prometheus import PrometheusCollector


@pytest.fixture
def incident() -> InvestigationRequest:
    return InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2026, 10, 21, 10, tzinfo=UTC),
        end_time=datetime(2026, 10, 21, 10, 0, 10, tzinfo=UTC),
    )


def log_line(incident: InvestigationRequest) -> str:
    return (
        json.dumps(
            {
                "timestamp": incident.start_time.isoformat(),
                "service": incident.service,
                "environment": incident.environment,
                "level": "ERROR",
                "message": "Payment timeout",
            }
        )
        + "\n"
    )


def test_collection_time_uses_monotonic_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter([1_000_000_000, 1_025_000_000])
    monkeypatch.setattr(collection_module, "perf_counter_ns", lambda: next(ticks))
    measured = collect_source(
        EvidenceSource.METRIC,
        lambda: CollectionResult(status=CollectionStatus.EMPTY),
        disabled_reason="Not configured",
    )
    assert measured.metadata.duration_ms == 25
    assert measured.metadata.status == CollectionStatus.EMPTY


def test_disabled_source_is_not_a_measured_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_clock() -> int:
        pytest.fail("Disabled sources must not be timed")

    monkeypatch.setattr(collection_module, "perf_counter_ns", unexpected_clock)
    measured = collect_source(EvidenceSource.METRIC, None, disabled_reason="Not configured")
    assert measured.metadata.status == CollectionStatus.DISABLED
    assert measured.metadata.duration_ms is None
    assert measured.metadata.evidence_count == 0


def test_legacy_recorded_collection_outcome_is_not_guessed() -> None:
    measured = collect_source(
        EvidenceSource.METRIC,
        lambda: CollectionResult(issues=["Recorded note"]),
        disabled_reason="Not configured",
    )
    assert measured.metadata.status == CollectionStatus.NOT_RECORDED


@pytest.mark.parametrize(
    "case, expected",
    [
        ("valid", CollectionStatus.COLLECTED),
        ("empty", CollectionStatus.EMPTY),
        ("missing", CollectionStatus.ERROR),
        ("corrupt", CollectionStatus.PARTIAL),
        ("corrupt_only", CollectionStatus.PARTIAL),
        ("limit", CollectionStatus.PARTIAL),
    ],
)
def test_log_outcomes_are_explicit(
    tmp_path: Path,
    incident: InvestigationRequest,
    case: str,
    expected: CollectionStatus,
) -> None:
    path = tmp_path / "logs.jsonl"
    if case != "missing":
        text = "" if case == "empty" else log_line(incident)
        if case == "corrupt":
            text += "invalid JSON\n"
        if case == "corrupt_only":
            text = "invalid JSON\n"
        if case == "limit":
            text += log_line(incident)
        path.write_text(text, encoding="utf-8")
    result = collect_logs(path, incident, max_evidence=1)
    assert result.status == expected
    if case == "corrupt_only":
        assert result.evidence == []
        assert result.issues


@pytest.mark.parametrize(
    "case, expected",
    [
        ("complete", CollectionStatus.COLLECTED),
        ("empty", CollectionStatus.EMPTY),
        ("partial", CollectionStatus.PARTIAL),
        ("failed", CollectionStatus.ERROR),
        ("annotation", CollectionStatus.PARTIAL),
        ("sparse", CollectionStatus.PARTIAL),
        ("skipped", CollectionStatus.SKIPPED),
    ],
)
def test_metric_outcomes(
    incident: InvestigationRequest,
    case: str,
    expected: CollectionStatus,
) -> None:
    if case == "skipped":
        incident.end_time += timedelta(hours=2)

    def respond(request: httpx.Request) -> httpx.Response:
        assert case != "skipped"
        if case == "failed" or (case == "partial" and "jvm_memory" in request.url.params["query"]):
            return httpx.Response(503)
        samples = [
            [incident.start_time.timestamp(), "1"],
            [incident.start_time.timestamp() + 5, "1"],
        ]
        if case == "sparse":
            samples = samples[:1]
        payload: dict[str, object] = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [] if case == "empty" else [{"values": samples}],
            },
        }
        if case == "annotation":
            payload["warnings"] = ["Partial response"]
        return httpx.Response(200, json=payload)

    with httpx.Client(
        base_url="http://prometheus:9090", transport=httpx.MockTransport(respond)
    ) as client:
        result = PrometheusCollector(client).collect(incident)
    assert result.status == expected


@pytest.mark.parametrize(
    "case, expected",
    [
        ("up", CollectionStatus.COLLECTED),
        ("down", CollectionStatus.COLLECTED),
        ("health_failure", CollectionStatus.PARTIAL),
        ("identity_failure", CollectionStatus.ERROR),
        ("other_target", CollectionStatus.SKIPPED),
    ],
)
def test_actuator_collection_status_is_not_business_health(
    incident: InvestigationRequest,
    case: str,
    expected: CollectionStatus,
) -> None:
    target = ActuatorTarget.model_validate(
        {
            "base_url": "http://orders:8081/actuator/",
            "service": "order-service",
            "environment": "local",
        }
    )
    if case == "other_target":
        incident.service = "another-service"

    def respond(request: httpx.Request) -> httpx.Response:
        assert case != "other_target"
        if request.url.path.endswith("info"):
            return httpx.Response(
                200,
                json={
                    "app": {
                        "name": "wrong" if case == "identity_failure" else "order-service",
                        "environment": "local",
                        "version": "0.1.0",
                    }
                },
            )
        if case == "health_failure":
            return httpx.Response(502)
        return httpx.Response(
            503 if case == "down" else 200, json={"status": "DOWN" if case == "down" else "UP"}
        )

    with httpx.Client(
        base_url=str(target.base_url), transport=httpx.MockTransport(respond)
    ) as client:
        result = HttpActuatorCollector(client, target).collect(incident)
    assert result.status == expected
    if case in {"up", "down"}:
        assert result.issues  # Snapshot limitations must not turn a successful read into partial.
        assert len(result.evidence) == 2


def test_pipeline_preserves_disabled_status_and_durations(
    tmp_path: Path,
    incident: InvestigationRequest,
) -> None:
    path = tmp_path / "logs.jsonl"
    path.write_text(log_line(incident), encoding="utf-8")
    report = investigate(incident, log_path=path)
    assert report.source_collections is not None
    statuses = {item.source: item for item in report.source_collections}
    assert statuses[EvidenceSource.LOG].status == CollectionStatus.COLLECTED
    assert statuses[EvidenceSource.LOG].duration_ms is not None
    assert statuses[EvidenceSource.METRIC].status == CollectionStatus.DISABLED
    assert statuses[EvidenceSource.ACTUATOR].duration_ms is None
    assert report.analysis_status == "not_requested"


def test_legacy_report_does_not_gain_fabricated_metadata() -> None:
    payload = {
        "analysis_status": "not_requested",
        "summary": "Legacy report",
        "evidence": [],
        "findings": [],
        "hypotheses": [],
        "recommended_checks": [],
        "missing_data": ["Source details were not recorded"],
    }
    report = InvestigationReport.model_validate(payload)
    assert report.source_collections is None
    assert report.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "status, count, duration, issues",
    [
        ("collected", 0, 1, []),
        ("error", 1, 1, ["Read failed"]),
        ("disabled", 0, 0, ["Not configured"]),
        ("empty", 0, None, []),
        ("partial", 0, 1, []),
    ],
)
def test_inconsistent_collection_metadata_is_rejected(
    status: str,
    count: int,
    duration: int | None,
    issues: list[str],
) -> None:
    with pytest.raises(ValidationError):
        SourceCollection.model_validate(
            {
                "source": "log",
                "status": status,
                "evidence_count": count,
                "duration_ms": duration,
                "issues": issues,
            }
        )


@pytest.mark.parametrize("case", ["duplicate_source", "wrong_count"])
def test_report_rejects_inconsistent_source_metadata(case: str) -> None:
    collection: dict[str, object] = {
        "source": "log",
        "status": "not_recorded",
        "evidence_count": 1 if case == "wrong_count" else 0,
        "duration_ms": None,
        "issues": [],
    }
    with pytest.raises(ValidationError):
        InvestigationReport.model_validate(
            {
                "summary": "No matching records",
                "evidence": [],
                "findings": [],
                "hypotheses": [],
                "recommended_checks": [],
                "missing_data": ["No matching records"],
                "source_collections": (
                    [collection, collection] if case == "duplicate_source" else [collection]
                ),
            }
        )
