from collections.abc import Iterator, Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine

import ai_incident_investigator.main as main_module
from ai_incident_investigator.dependencies import get_analyzer, get_investigation_store
from ai_incident_investigator.investigations.analysis import Analysis, AnalysisError
from ai_incident_investigator.investigations.ports import StorageError
from ai_incident_investigator.investigations.records import StoredInvestigation
from ai_incident_investigator.investigations.reports import Evidence, InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.storage.repository import SqlAlchemyInvestigationStore


@pytest.fixture
def payload() -> dict[str, object]:
    return {
        "service": "order-service",
        "environment": "local",
        "start_time": "2026-10-19T10:00:00Z",
        "end_time": "2026-10-19T10:05:00Z",
        "description": "Orders are failing.",
    }


@pytest.fixture
def client(
    app: FastAPI,
    storage_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("INVESTIGATOR_LOG_PATH", str(tmp_path / "missing.jsonl"))
    store = SqlAlchemyInvestigationStore(storage_engine)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_investigation_store] = lambda: store
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_post_preserves_contract_and_saved_report_can_be_loaded(
    client: TestClient, payload: dict[str, object]
) -> None:
    response = client.post("/investigations", json=payload)

    assert response.status_code == 200
    report = InvestigationReport.model_validate(response.json())
    identifier = UUID(response.headers["X-Investigation-ID"])
    saved_response = client.get(f"/investigations/{identifier}")
    assert saved_response.status_code == 200
    saved = StoredInvestigation.model_validate(saved_response.json())
    assert saved.report == report
    assert saved.request == InvestigationRequest.model_validate(payload)
    assert saved.duration_ms >= 0
    assert saved.configured_model is None
    assert saved.prompt_sha256 is None


def test_unknown_saved_investigation_returns_404(client: TestClient) -> None:
    assert client.get(f"/investigations/{uuid4()}").status_code == 404


def test_malformed_saved_id_returns_422(client: TestClient) -> None:
    assert client.get("/investigations/not-a-uuid").status_code == 422


def test_storage_is_optional_and_disabled_reads_return_503(
    app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]
) -> None:
    monkeypatch.setenv("INVESTIGATOR_LOG_PATH", str(tmp_path / "missing.jsonl"))
    with TestClient(app) as client:
        response = client.post("/investigations", json=payload)
        assert response.status_code == 200
        assert "X-Investigation-ID" not in response.headers
        assert client.get(f"/investigations/{uuid4()}").status_code == 503


class UnavailableStore:
    def save(self, record: StoredInvestigation) -> None:
        raise StorageError("private database credentials and payload")

    def get(self, investigation_id: UUID) -> StoredInvestigation | None:
        raise StorageError("private database credentials and payload")


@pytest.mark.parametrize("method", ["POST", "GET"])
def test_storage_failure_returns_503_without_private_details(
    app: FastAPI, client: TestClient, payload: dict[str, object], method: str
) -> None:
    app.dependency_overrides[get_investigation_store] = UnavailableStore
    url = "/investigations" if method == "POST" else f"/investigations/{uuid4()}"
    response = client.request(method, url, json=payload if method == "POST" else None)
    assert response.status_code == 503
    assert "private" not in response.text
    assert "X-Investigation-ID" not in response.headers


def test_investigation_remains_after_application_restart(
    app: FastAPI,
    storage_engine: Engine,
    payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/investigator_test")
    monkeypatch.setenv("INVESTIGATOR_LOG_PATH", str(tmp_path / "missing.jsonl"))

    def new_engine(value: SecretStr) -> Engine:
        return create_engine(storage_engine.url)

    monkeypatch.setattr(main_module, "create_database_engine", new_engine)
    with TestClient(app) as first_client:
        response = first_client.post("/investigations", json=payload)
        assert response.status_code == 200
        identifier = response.headers["X-Investigation-ID"]
    assert app.state.investigation_store is None
    with TestClient(app) as second_client:
        loaded = second_client.get(f"/investigations/{identifier}")
        assert loaded.status_code == 200
        assert loaded.json()["report"] == response.json()


def test_startup_requires_applied_migrations(
    app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://test:private@localhost/investigator_test"
    )

    def empty_database(value: SecretStr) -> Engine:
        return create_engine(f"sqlite:///{tmp_path / 'unmigrated.db'}")

    monkeypatch.setattr(main_module, "create_database_engine", empty_database)
    with pytest.raises(RuntimeError, match="apply migrations") as captured, TestClient(app):
        pass
    assert "private" not in str(captured.value)
    assert app.state.investigation_store is None


class MustNotBeCalledAnalyzer:
    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis:
        raise AnalysisError("Empty evidence must skip analysis")


def test_configured_model_is_metadata_not_proof_of_a_model_call(
    app: FastAPI, client: TestClient, payload: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "configured-test-model")
    app.dependency_overrides[get_analyzer] = MustNotBeCalledAnalyzer
    response = client.post("/investigations", json=payload)
    assert response.status_code == 200
    assert response.json()["analysis_status"] == "skipped"
    saved = client.get(f"/investigations/{response.headers['X-Investigation-ID']}").json()
    assert saved["configured_model"] == "configured-test-model"
    assert len(saved["prompt_sha256"]) == 64


class TrackingAnalyzer:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.calls = 0

    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis:
        self.calls += 1
        if self.fail:
            raise AnalysisError("Simulated provider failure")
        return Analysis.model_validate(
            {
                "summary": "An order timeout was recorded; its cause is not yet known.",
                "findings": [
                    {
                        "statement": "The service logged an order timeout.",
                        "evidence_ids": [evidence[0].id],
                    }
                ],
                "hypotheses": [],
                "recommended_checks": [
                    {
                        "action": "Inspect downstream payment availability.",
                        "reason": "The log alone does not explain the timeout.",
                    }
                ],
            }
        )


@pytest.mark.parametrize("analysis_fails", [False, True])
def test_saved_analysis_retains_evidence_and_get_does_not_repeat_analysis(
    app: FastAPI,
    client: TestClient,
    payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    analysis_fails: bool,
) -> None:
    log_path = tmp_path / "incident.jsonl"
    log_path.write_text(
        '{"timestamp":"2026-10-19T10:02:00Z","service":"order-service",'
        '"environment":"local","level":"ERROR","message":"Order payment timed out"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("INVESTIGATOR_LOG_PATH", str(log_path))
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    analyzer = TrackingAnalyzer(fail=analysis_fails)
    app.dependency_overrides[get_analyzer] = lambda: analyzer

    response = client.post("/investigations", json=payload)
    assert response.status_code == 200
    report = InvestigationReport.model_validate(response.json())
    assert report.analysis_status == ("failed" if analysis_fails else "completed")
    assert len(report.evidence) == 1
    assert analyzer.calls == 1

    log_path.unlink()
    saved_response = client.get(f"/investigations/{response.headers['X-Investigation-ID']}")
    assert saved_response.status_code == 200
    saved = StoredInvestigation.model_validate(saved_response.json())
    assert saved.report == report
    history = client.get("/investigations")
    assert history.status_code == 200
    assert history.json()["items"][0]["id"] == str(saved.id)
    assert history.json()["items"][0]["analysis_status"] == report.analysis_status
    assert analyzer.calls == 1
