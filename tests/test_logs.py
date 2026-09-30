import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.sources.logs import LogEntry, collect_logs


@pytest.fixture
def request_model() -> InvestigationRequest:
    return InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
        end_time=datetime(2026, 9, 19, 10, 10, tzinfo=UTC),
    )


def make_line(**changes: object) -> str:
    payload: dict[str, object] = {
        "timestamp": "2026-09-19T10:00:00Z",
        "service": "order-service",
        "environment": "local",
        "level": "ERROR",
        "message": "Payment request timed out.",
    }
    payload.update(changes)
    return json.dumps(payload)


def test_filters_and_preserves_line_references(
    tmp_path: Path, request_model: InvestigationRequest
) -> None:
    path = tmp_path / "logs.jsonl"
    path.write_text(
        "\n".join(
            [
                make_line(),
                make_line(service="payment-service"),
                make_line(environment="production"),
                make_line(timestamp="2026-09-19T09:59:59Z"),
                make_line(timestamp="2026-09-19T10:10:00Z"),
                make_line(timestamp="2026-09-19T13:05:00+03:00", level="INFO"),
            ]
        ),
        encoding="utf-8",
    )

    result = collect_logs(path, request_model)

    assert [item.id for item in result.evidence] == ["log-1", "log-6"]
    assert result.evidence[1].reference == "local-jsonl:line:6"
    assert result.evidence[1].start_time.tzinfo == UTC
    assert result.evidence[1].summary.startswith("[INFO]")
    assert result.issues == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timestamp", "2026-09-19T10:00:00"),
        ("timestamp", 1789812000),
        ("service", "   "),
        ("level", "UNKNOWN"),
        ("message", ""),
    ],
)
def test_invalid_log_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        LogEntry.model_validate_json(make_line(**{field: value}))


def test_bad_lines_are_reported_without_losing_good_records(
    tmp_path: Path, request_model: InvestigationRequest
) -> None:
    path = tmp_path / "logs.jsonl"
    path.write_bytes(b"not json\n\xff\n\n" + make_line().encode("utf-8"))

    result = collect_logs(path, request_model)

    assert [item.id for item in result.evidence] == ["log-4"]
    assert any("Skipped 2 invalid" in issue for issue in result.issues)


def test_unavailable_file_differs_from_no_matches(
    tmp_path: Path, request_model: InvestigationRequest
) -> None:
    path = tmp_path / "logs.jsonl"
    unavailable = collect_logs(path, request_model)
    path.write_text(make_line(service="other-service"), encoding="utf-8")
    no_matches = collect_logs(path, request_model)

    assert unavailable.evidence == no_matches.evidence == []
    assert any("could not be read" in issue for issue in unavailable.issues)
    assert any("no matching records" in issue for issue in no_matches.issues)


def test_evidence_limit_reports_omitted_records(
    tmp_path: Path, request_model: InvestigationRequest
) -> None:
    path = tmp_path / "logs.jsonl"
    path.write_text(make_line() + "\n" + make_line(), encoding="utf-8")

    result = collect_logs(path, request_model, max_evidence=1)

    assert len(result.evidence) == 1
    assert any("Evidence limit" in issue for issue in result.issues)


@pytest.mark.parametrize(
    ("limits", "expected"),
    [
        ({"max_scan_bytes": 10}, "Log scan byte limit"),
        ({"max_line_bytes": 10}, "exceeds the byte limit"),
    ],
)
def test_byte_limits_are_reported(
    tmp_path: Path,
    request_model: InvestigationRequest,
    limits: dict[str, int],
    expected: str,
) -> None:
    path = tmp_path / "logs.jsonl"
    path.write_text(make_line(), encoding="utf-8")

    result = collect_logs(path, request_model, **limits)

    assert result.evidence == []
    assert any(expected in issue for issue in result.issues)
