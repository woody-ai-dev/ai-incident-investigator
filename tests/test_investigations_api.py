import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_incident_investigator.investigations.reports import InvestigationReport
from ai_incident_investigator.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("INVESTIGATOR_LOG_PATH", str(tmp_path / "missing.jsonl"))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def valid_payload() -> dict[str, object]:
    return {
        "service": "order-service",
        "environment": "local",
        "start_time": "2026-09-19T10:00:00Z",
        "end_time": "2026-09-19T10:10:00Z",
        "description": "Users cannot create orders.",
    }


@pytest.mark.parametrize("service", ["order-service", "payment-service"])
def test_investigation_returns_inconclusive_report(
    client: TestClient,
    valid_payload: dict[str, object],
    service: str,
) -> None:
    valid_payload["service"] = service

    response = client.post("/investigations", json=valid_payload)

    assert response.status_code == 200
    report = InvestigationReport.model_validate(response.json())
    assert service in report.summary
    assert "local" in report.summary
    assert "2026-09-19T10:00:00+00:00" in report.summary
    assert "2026-09-19T10:10:00+00:00" in report.summary
    assert report.evidence == []
    assert report.findings == []
    assert report.hypotheses == []
    assert report.missing_data
    assert report.recommended_checks


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service", "   "),
        ("end_time", "2026-09-19T09:59:00Z"),
        ("end_time", "2026-09-19T10:00:00Z"),
        ("start_time", "2026-09-19T10:00:00"),
        ("unexpected", "value"),
    ],
)
def test_invalid_request_returns_422(
    client: TestClient,
    valid_payload: dict[str, object],
    field: str,
    value: object,
) -> None:
    valid_payload[field] = value

    response = client.post("/investigations", json=valid_payload)

    assert response.status_code == 422
    assert response.json()["detail"]


def test_missing_service_returns_422(
    client: TestClient,
    valid_payload: dict[str, object],
) -> None:
    del valid_payload["service"]

    response = client.post("/investigations", json=valid_payload)

    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", "service"] and error["type"] == "missing"
        for error in response.json()["detail"]
    )


def test_api_returns_log_evidence(
    client: TestClient,
    valid_payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "logs.jsonl"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-09-19T10:03:00Z",
                "service": "order-service",
                "environment": "local",
                "level": "ERROR",
                "message": "Payment request timed out.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INVESTIGATOR_LOG_PATH", str(path))

    response = client.post("/investigations", json=valid_payload)

    assert response.status_code == 200
    report = InvestigationReport.model_validate(response.json())
    assert len(report.evidence) == 1
    assert report.evidence[0].summary == "[ERROR] Payment request timed out."
    assert report.evidence[0].reference == "local-jsonl:line:1"
    assert report.hypotheses == []
    assert not any("Log file could not be read" in issue for issue in report.missing_data)
