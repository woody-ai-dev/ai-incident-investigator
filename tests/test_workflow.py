from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from ai_incident_investigator.investigations.analysis import Analysis, AnalysisError
from ai_incident_investigator.investigations.ports import StorageError
from ai_incident_investigator.investigations.records import StoredInvestigation
from ai_incident_investigator.investigations.reports import Evidence
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.workflow import (
    AnalysisConfiguration,
    execute_investigation,
)


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[UUID, StoredInvestigation] = {}
        self.saves = 0

    def save(self, record: StoredInvestigation) -> None:
        self.saves += 1
        self.records[record.id] = record

    def get(self, investigation_id: UUID) -> StoredInvestigation | None:
        return self.records.get(investigation_id)


class CheckingAnalyzer:
    def __init__(self, store: MemoryStore, *, fail: bool = False) -> None:
        self.store = store
        self.fail = fail
        self.calls = 0

    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis:
        assert not self.store.records
        assert self.store.saves == 0
        self.calls += 1
        if self.fail:
            raise AnalysisError("Simulated analysis failure")
        return Analysis.model_validate(
            {
                "summary": "The service logged an order timeout; its cause is unknown.",
                "findings": [
                    {"statement": "An order timeout was logged.", "evidence_ids": [evidence[0].id]}
                ],
                "hypotheses": [],
                "recommended_checks": [
                    {
                        "action": "Check downstream payment logs.",
                        "reason": "The cause is not established by this observation.",
                    }
                ],
            }
        )


@pytest.fixture
def request_model() -> InvestigationRequest:
    return InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2026, 10, 19, 10, tzinfo=UTC),
        end_time=datetime(2026, 10, 19, 10, 5, tzinfo=UTC),
    )


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    path = tmp_path / "incident.jsonl"
    path.write_text(
        '{"timestamp":"2026-10-19T10:02:00Z","service":"order-service",'
        '"environment":"local","level":"ERROR","message":"Order payment timed out"}\n',
        encoding="utf-8",
    )
    return path


def test_workflow_without_storage_returns_report_and_no_id(
    request_model: InvestigationRequest, log_path: Path
) -> None:
    execution = execute_investigation(request_model, log_path=log_path)
    assert execution.investigation_id is None
    assert execution.report.analysis_status == "not_requested"
    assert len(execution.report.evidence) == 1


@pytest.mark.parametrize("analysis_fails", [False, True])
def test_workflow_saves_only_after_analysis_and_preserves_result(
    request_model: InvestigationRequest, log_path: Path, analysis_fails: bool
) -> None:
    store = MemoryStore()
    analyzer = CheckingAnalyzer(store, fail=analysis_fails)
    configuration = AnalysisConfiguration(configured_model="test-model", prompt_sha256="a" * 64)
    execution = execute_investigation(
        request_model,
        log_path=log_path,
        analyzer=analyzer,
        store=store,
        analysis_configuration=configuration,
    )
    assert analyzer.calls == 1
    assert store.saves == 1
    assert execution.investigation_id is not None
    saved = store.get(execution.investigation_id)
    assert saved is not None
    assert saved.request == request_model
    assert saved.report == execution.report
    assert saved.report.analysis_status == ("failed" if analysis_fails else "completed")
    assert len(saved.report.evidence) == 1
    assert saved.configured_model == "test-model"
    assert saved.prompt_sha256 == "a" * 64
    assert saved.duration_ms >= 0


def test_skipped_analysis_keeps_configuration_without_calling_provider(
    request_model: InvestigationRequest, tmp_path: Path
) -> None:
    store = MemoryStore()
    analyzer = CheckingAnalyzer(store)
    execution = execute_investigation(
        request_model,
        log_path=tmp_path / "missing.jsonl",
        analyzer=analyzer,
        store=store,
        analysis_configuration=AnalysisConfiguration("configured-model", "b" * 64),
    )
    assert analyzer.calls == 0
    assert execution.report.analysis_status == "skipped"
    assert execution.investigation_id is not None
    assert store.records[execution.investigation_id].configured_model == "configured-model"


def test_failed_save_propagates_and_does_not_retry_analysis(
    request_model: InvestigationRequest, log_path: Path
) -> None:
    class FailingStore(MemoryStore):
        def save(self, record: StoredInvestigation) -> None:
            self.saves += 1
            raise StorageError("Simulated database failure")

    store = FailingStore()
    analyzer = CheckingAnalyzer(store)
    with pytest.raises(StorageError, match="Simulated database failure"):
        execute_investigation(request_model, log_path=log_path, analyzer=analyzer, store=store)
    assert analyzer.calls == 1
    assert store.saves == 1
    assert not store.records
