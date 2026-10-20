from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text, update

from ai_incident_investigator.investigations.ports import StorageError
from ai_incident_investigator.investigations.records import StoredInvestigation
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate
from ai_incident_investigator.storage.models import InvestigationRow
from ai_incident_investigator.storage.repository import SqlAlchemyInvestigationStore


@pytest.fixture
def record(tmp_path: Path) -> StoredInvestigation:
    request = InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2026, 10, 19, 10, tzinfo=UTC),
        end_time=datetime(2026, 10, 19, 10, 5, tzinfo=UTC),
        description="Проверка сохранения расследования.",
    )
    log_path = tmp_path / "logs.jsonl"
    log_path.write_text(
        '{"timestamp":"2026-10-19T10:02:00Z","service":"order-service",'
        '"environment":"local","level":"ERROR","message":"Simulated timeout"}\n',
        encoding="utf-8",
    )
    return StoredInvestigation(
        duration_ms=123,
        request=request,
        report=investigate(request, log_path=log_path),
    )


def test_snapshot_round_trip(storage_engine: Engine, record: StoredInvestigation) -> None:
    store = SqlAlchemyInvestigationStore(storage_engine)

    store.check_ready()
    store.save(record)
    loaded = store.get(record.id)

    assert loaded == record
    assert loaded is not None
    assert loaded.report.evidence == record.report.evidence
    assert loaded.report.missing_data == record.report.missing_data


def test_missing_id_returns_none(storage_engine: Engine) -> None:
    assert SqlAlchemyInvestigationStore(storage_engine).get(uuid4()) is None


def test_incomplete_schema_is_not_ready(storage_engine: Engine) -> None:
    with storage_engine.begin() as connection:
        connection.execute(text("ALTER TABLE investigations DROP COLUMN report_payload"))
    with pytest.raises(StorageError, match="not migrated"):
        SqlAlchemyInvestigationStore(storage_engine).check_ready()


def test_commit_survives_new_engine(storage_engine: Engine, record: StoredInvestigation) -> None:
    SqlAlchemyInvestigationStore(storage_engine).save(record)
    other_engine = create_engine(storage_engine.url)
    try:
        assert SqlAlchemyInvestigationStore(other_engine).get(record.id) == record
    finally:
        other_engine.dispose()


def test_duplicate_id_rolls_back_and_store_remains_usable(
    storage_engine: Engine, record: StoredInvestigation
) -> None:
    store = SqlAlchemyInvestigationStore(storage_engine)
    store.save(record)
    duplicate = record.model_copy(update={"duration_ms": 999})

    with pytest.raises(StorageError, match="could not be saved"):
        store.save(duplicate)

    assert store.get(record.id) == record
    another = record.model_copy(update={"id": uuid4()})
    store.save(another)
    assert store.get(another.id) == another


def test_corrupt_saved_payload_is_rejected(
    storage_engine: Engine, record: StoredInvestigation
) -> None:
    store = SqlAlchemyInvestigationStore(storage_engine)
    store.save(record)
    with storage_engine.begin() as connection:
        connection.execute(
            update(InvestigationRow)
            .where(InvestigationRow.id == record.id)
            .values(report_payload={"summary": "incomplete private report"})
        )

    with pytest.raises(StorageError, match="could not be loaded"):
        store.get(record.id)


def test_migration_matches_models_and_can_be_reapplied(storage_engine: Engine) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with storage_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.check(config)
        command.downgrade(config, "base")
        assert "investigations" not in inspect(connection).get_table_names()
        command.upgrade(config, "head")
    SqlAlchemyInvestigationStore(storage_engine).check_ready()


def test_postgres_uses_jsonb(storage_engine: Engine) -> None:
    if storage_engine.dialect.name != "postgresql":
        pytest.skip("JSONB is a PostgreSQL-specific storage type")
    with storage_engine.connect() as connection:
        types = connection.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'investigations' "
                "AND column_name IN ('request_payload', 'report_payload')"
            )
        ).all()
    assert {name: data_type for name, data_type in types} == {
        "request_payload": "jsonb",
        "report_payload": "jsonb",
    }
