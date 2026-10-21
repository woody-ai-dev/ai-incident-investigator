from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, select

from ai_incident_investigator.investigations.records import StoredInvestigation
from ai_incident_investigator.investigations.reports import InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate
from ai_incident_investigator.storage.models import InvestigationRow
from ai_incident_investigator.storage.repository import SqlAlchemyInvestigationStore


def test_new_and_legacy_snapshots_keep_their_metadata(
    storage_engine: Engine,
    tmp_path: Path,
) -> None:
    request = InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2026, 10, 21, 10, tzinfo=UTC),
        end_time=datetime(2026, 10, 21, 11, tzinfo=UTC),
    )
    report = investigate(request, log_path=tmp_path / "missing.jsonl")
    store = SqlAlchemyInvestigationStore(storage_engine)
    new = StoredInvestigation(duration_ms=5, request=request, report=report)
    store.save(new)
    assert store.get(new.id) == new

    legacy_payload = report.model_dump(mode="json", exclude={"source_collections"})
    legacy = StoredInvestigation(
        duration_ms=5, request=request, report=InvestigationReport.model_validate(legacy_payload)
    )
    store.save(legacy)
    loaded = store.get(legacy.id)
    assert loaded is not None
    assert loaded.report.model_dump(mode="json") == legacy_payload
    with storage_engine.connect() as connection:
        raw = connection.execute(
            select(InvestigationRow.report_payload).where(InvestigationRow.id == legacy.id)
        ).scalar_one()
    assert raw == legacy_payload
