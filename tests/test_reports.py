from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_incident_investigator.investigations.reports import Evidence, InvestigationReport


@pytest.fixture
def evidence_payload() -> dict[str, object]:
    return {
        "id": "e1",
        "source": "log",
        "service": "order-service",
        "summary": "Payment request timed out.",
        "reference": "logs/order-service.jsonl:42",
        "start_time": "2026-09-19T13:03:00+03:00",
    }


@pytest.fixture
def report_payload(evidence_payload: dict[str, object]) -> dict[str, object]:
    return {
        "summary": "An order request failed while waiting for payment-service.",
        "evidence": [evidence_payload],
        "findings": [
            {
                "statement": "A payment timeout was recorded.",
                "evidence_ids": ["e1"],
            }
        ],
        "hypotheses": [
            {
                "statement": "The payment dependency may be responding slowly.",
                "supporting_evidence_ids": ["e1"],
            }
        ],
        "recommended_checks": [
            {
                "action": "Inspect the payment request trace.",
                "reason": "Locate the operation responsible for the delay.",
            }
        ],
        "missing_data": ["The request trace is unavailable."],
    }


def test_valid_report_round_trip(report_payload: dict[str, object]) -> None:
    report = InvestigationReport.model_validate(report_payload)

    assert report.findings[0].evidence_ids == ["e1"]
    assert report.evidence[0].start_time == datetime(2026, 9, 19, 10, 3, tzinfo=UTC)
    assert report.evidence[0].start_time.tzinfo == UTC
    assert report.evidence[0].end_time is None
    assert report.hypotheses[0].contradicting_evidence_ids == []

    restored = InvestigationReport.model_validate_json(report.model_dump_json())

    assert restored == report


def test_evidence_can_describe_an_inverval(
    evidence_payload: dict[str, object],
) -> None:
    evidence_payload["end_time"] = "2026-09-19T10:05:00Z"

    evidence = Evidence.model_validate(evidence_payload)

    assert evidence.end_time == datetime(2026, 9, 19, 10, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "   "),
        ("summary", ""),
        ("reference", ""),
        ("source", "unknown"),
        ("start_time", None),
        ("start_time", "2026-09-19T10:03:00"),
        ("start_time", 1789812000),
        ("end_time", "2026-09-19T10:05:00"),
        ("end_time", "2026-09-19T10:03:00Z"),
        ("end_time", "2026-09-19T10:02:00Z"),
    ],
)
def test_invalid_evidence_is_rejected(
    evidence_payload: dict[str, object],
    field: str,
    value: object,
) -> None:
    evidence_payload[field] = value

    with pytest.raises(ValidationError):
        Evidence.model_validate(evidence_payload)


def test_duplicate_evidence_ids_are_rejected(
    report_payload: dict[str, object],
    evidence_payload: dict[str, object],
) -> None:
    report_payload["evidence"] = [
        evidence_payload,
        dict(evidence_payload),
    ]

    with pytest.raises(ValidationError, match="evidence IDs must be unique"):
        InvestigationReport.model_validate(report_payload)


@pytest.mark.parametrize(
    ("section", "reference_field"),
    [
        ("findings", "evidence_ids"),
        ("hypotheses", "supporting_evidence_ids"),
        ("hypotheses", "contradicting_evidence_ids"),
    ],
)
def test_unknown_references_are_rejected(
    report_payload: dict[str, object],
    section: str,
    reference_field: str,
) -> None:
    item: dict[str, object] = {
        "statement": "A possible explanation.",
    }

    if section == "hypotheses":
        item["supporting_evidence_ids"] = ["e1"]

    item[reference_field] = ["missing-id"]
    report_payload[section] = [item]

    with pytest.raises(ValidationError, match="unknown evidence IDs: missing-id"):
        InvestigationReport.model_validate(report_payload)


def test_finding_requires_evidence(report_payload: dict[str, object]) -> None:
    report_payload["findings"] = [
        {
            "statement": "A timeout occurred.",
            "evidence_ids": [],
        }
    ]

    with pytest.raises(ValidationError):
        InvestigationReport.model_validate(report_payload)


def test_inconclusive_report_is_allowed(
    report_payload: dict[str, object],
) -> None:
    report_payload.update(
        summary="There is not enough evidence to investigate.",
        evidence=[],
        findings=[],
        hypotheses=[],
    )

    report = InvestigationReport.model_validate(report_payload)

    assert report.hypotheses == []
    assert report.missing_data


def test_no_evidence_requires_an_explanation(
    report_payload: dict[str, object],
) -> None:
    report_payload.update(
        evidence=[],
        findings=[],
        hypotheses=[],
        missing_data=[],
    )

    with pytest.raises(ValidationError, match="missing_data must explain"):
        InvestigationReport.model_validate(report_payload)


def test_report_sections_must_be_explicit(
    report_payload: dict[str, object],
) -> None:
    del report_payload["findings"]

    with pytest.raises(ValidationError):
        InvestigationReport.model_validate(report_payload)
