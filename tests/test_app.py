from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_incident_investigator.dependencies import get_metrics_collector
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.main import create_app
from ai_incident_investigator.sources.metrics import MetricsCollection


def test_app_factory_isolates_overrides_and_lifecycle_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATOR_LOG_PATH", str(tmp_path / "missing.jsonl"))
    first_app = create_app()
    second_app = create_app()
    marker = "Only the first application has this collector."

    class FakeCollector:
        def collect(self, request: InvestigationRequest) -> MetricsCollection:
            return MetricsCollection(issues=[marker])

    first_app.dependency_overrides[get_metrics_collector] = FakeCollector
    payload = {
        "service": "order-service",
        "environment": "local",
        "start_time": "2026-10-19T10:00:00Z",
        "end_time": "2026-10-19T10:05:00Z",
    }
    try:
        with TestClient(first_app) as first_client, TestClient(second_app) as second_client:
            first_app.state.instance_marker = "first"
            assert not hasattr(second_app.state, "instance_marker")
            first = first_client.post("/investigations", json=payload)
            second = second_client.post("/investigations", json=payload)
            assert first.status_code == second.status_code == 200
            assert marker in first.json()["missing_data"]
            assert marker not in second.json()["missing_data"]
            assert not second_app.dependency_overrides
    finally:
        first_app.dependency_overrides.clear()
