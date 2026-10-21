from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, update

from ai_incident_investigator.dependencies import get_investigation_store
from ai_incident_investigator.investigations.history import (
    HistoryCursor,
    InvestigationPage,
    InvestigationQuery,
)
from ai_incident_investigator.investigations.ports import StorageError
from ai_incident_investigator.investigations.records import StoredInvestigation
from ai_incident_investigator.investigations.reports import InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.storage.models import InvestigationRow
from ai_incident_investigator.storage.repository import SqlAlchemyInvestigationStore

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


def snapshot(
    *, number: int, service: str = "orders", environment: str = "local"
) -> StoredInvestigation:
    return StoredInvestigation(
        id=UUID(int=number),
        created_at=NOW,
        duration_ms=123,
        request=InvestigationRequest(
            service=service,
            environment=environment,
            start_time=NOW - timedelta(hours=1),
            end_time=NOW,
        ),
        report=InvestigationReport(
            summary=f"Report {number}",
            evidence=[],
            findings=[],
            hypotheses=[],
            recommended_checks=[],
            missing_data=["Logs unavailable"],
        ),
    )


def test_empty_history(storage_engine: Engine) -> None:
    page = SqlAlchemyInvestigationStore(storage_engine).list_investigations(InvestigationQuery())
    assert page == InvestigationPage(items=[])


def test_cursor_order_ties_and_insert_between_pages(storage_engine: Engine) -> None:
    store = SqlAlchemyInvestigationStore(storage_engine)
    for number in [1, 4, 2, 3]:
        store.save(snapshot(number=number))
    first = store.list_investigations(InvestigationQuery(limit=2))
    assert [item.id.int for item in first.items] == [4, 3]
    assert first.next_cursor is not None
    store.save(snapshot(number=5))
    second = store.list_investigations(InvestigationQuery(limit=2, cursor=first.next_cursor))
    assert [item.id.int for item in second.items] == [2, 1]
    assert second.next_cursor is None
    assert "evidence" not in first.items[0].model_dump()
    assert first.items[0].analysis_status == "not_requested"


def test_combined_exact_filters_and_half_open_creation_dates(storage_engine: Engine) -> None:
    store = SqlAlchemyInvestigationStore(storage_engine)
    for number, service, environment, delta in [
        (1, "orders", "local", -1),
        (2, "orders", "local", 0),
        (3, "orders", "local", 1),
        (4, "orders", "prod", 0),
        (5, "payments", "local", 0),
        (6, "orders-new", "local", 0),
    ]:
        store.save(
            snapshot(number=number, service=service, environment=environment).model_copy(
                update={"created_at": NOW + timedelta(seconds=delta)}
            )
        )
    query = InvestigationQuery.model_validate(
        {
            "service": " orders ",
            "environment": "local",
            "created_from": "2026-10-20T15:00:00+03:00",
            "created_until": "2026-10-20T15:00:01+03:00",
        }
    )
    result = store.list_investigations(query)
    assert [item.id.int for item in result.items] == [2]
    assert result.items[0].created_at == NOW
    assert store.list_investigations(InvestigationQuery(service="' OR 1=1 --")).items == []


def test_history_uses_created_time_not_incident_time(storage_engine: Engine) -> None:
    store = SqlAlchemyInvestigationStore(storage_engine)
    store.save(snapshot(number=1))
    assert store.list_investigations(InvestigationQuery(created_from=NOW)).items
    assert not store.list_investigations(InvestigationQuery(created_until=NOW)).items


def test_microsecond_cursor_and_date_normalization(storage_engine: Engine) -> None:
    store = SqlAlchemyInvestigationStore(storage_engine)
    for number in [1, 2, 3]:
        store.save(
            snapshot(number=number).model_copy(
                update={"created_at": NOW + timedelta(microseconds=number)}
            )
        )
    ids: list[int] = []
    cursor = None
    while True:
        page = store.list_investigations(InvestigationQuery(limit=1, cursor=cursor))
        ids.extend(item.id.int for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert ids == [3, 2, 1]


def test_corrupt_history_is_a_storage_error(storage_engine: Engine) -> None:
    store = SqlAlchemyInvestigationStore(storage_engine)
    store.save(snapshot(number=1))
    with storage_engine.begin() as connection:
        connection.execute(update(InvestigationRow).values(report_payload={"summary": "private"}))
    with pytest.raises(StorageError, match="history could not be loaded"):
        store.list_investigations(InvestigationQuery())


def test_history_api_returns_only_summaries(app: FastAPI, storage_engine: Engine) -> None:
    store = SqlAlchemyInvestigationStore(storage_engine)
    store.save(snapshot(number=1))
    app.dependency_overrides[get_investigation_store] = lambda: store
    with TestClient(app) as client:
        response = client.get("/investigations", params={"service": "orders", "limit": 1})
    assert response.status_code == 200
    page = InvestigationPage.model_validate(response.json())
    assert [item.id.int for item in page.items] == [1]
    assert "report" not in response.json()["items"][0]
    assert page.next_cursor is None


@pytest.mark.parametrize(
    "query",
    [
        {"limit": "0"},
        {"limit": "101"},
        {"service": " "},
        {"environment": "x" * 101},
        {"created_from": "2026-10-20T12:00:00"},
        {"created_from": NOW.isoformat(), "created_until": NOW.isoformat()},
        {"cursor": "not-json"},
        {"cursor": "a" * 513},
        {"unexpected": "value"},
        {"cursor": HistoryCursor(created_at=NOW, id=uuid4()).encode() + "!"},
    ],
)
def test_history_rejects_invalid_queries(app: FastAPI, query: dict[str, str]) -> None:
    with TestClient(app) as client:
        assert client.get("/investigations", params=query).status_code == 422


def test_history_without_storage_returns_503(app: FastAPI) -> None:
    with TestClient(app) as client:
        assert client.get("/investigations").status_code == 503


def test_history_storage_errors_do_not_expose_details(app: FastAPI) -> None:
    class Unavailable:
        def list_investigations(self, query: InvestigationQuery) -> InvestigationPage:
            raise StorageError("private connection and credentials")

    app.dependency_overrides[get_investigation_store] = Unavailable
    with TestClient(app) as client:
        response = client.get("/investigations")
    assert response.status_code == 503
    assert "private" not in response.text


def test_upgrade_adds_history_index_without_changing_snapshots(storage_engine: Engine) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with storage_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0001_investigations")
    store = SqlAlchemyInvestigationStore(storage_engine)
    original = snapshot(number=1)
    store.save(original)
    with storage_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    assert store.get(original.id) == original
    assert [item.id for item in store.list_investigations(InvestigationQuery()).items] == [
        original.id
    ]
