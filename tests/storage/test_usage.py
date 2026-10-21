from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select

from ai_incident_investigator.investigations.ports import StorageError
from ai_incident_investigator.investigations.records import StoredInvestigation
from ai_incident_investigator.investigations.reports import InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.llm.accounting import capture_usage
from ai_incident_investigator.storage.models import InvestigationRow, LLMUsageRow
from ai_incident_investigator.storage.repository import SqlAlchemyInvestigationStore
from ai_incident_investigator.storage.usage import SqlAlchemyUsageReader
from ai_incident_investigator.usage.models import UsageQuery


def make_record(
    started_at: datetime, *, tokens: int | None = 1000, priced: bool = True
) -> StoredInvestigation:
    usage = capture_usage(
        {
            "model": "gpt-4.1-mini-2025-04-14" if priced else "unknown",
            "service_tier": "default",
            "usage": {
                "input_tokens": tokens,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens": 0,
                "total_tokens": tokens,
            }
            if tokens is not None
            else None,
        },
        requested_model="gpt-4.1-mini-2025-04-14",
        started_at=started_at,
        duration_ms=1000,
    )
    return StoredInvestigation(
        id=uuid4(),
        duration_ms=1500,
        request=InvestigationRequest(
            service="order-service",
            environment="local",
            start_time=started_at - timedelta(minutes=5),
            end_time=started_at,
        ),
        report=InvestigationReport(
            analysis_status="failed",
            summary="Analysis unavailable.",
            evidence=[],
            findings=[],
            hypotheses=[],
            recommended_checks=[],
            missing_data=["Logs unavailable."],
            llm_usage=usage,
        ),
    )


def test_usage_is_saved_atomically_and_round_trips(storage_engine: Engine) -> None:
    record = make_record(datetime.now(UTC) - timedelta(seconds=1))
    store = SqlAlchemyInvestigationStore(storage_engine)
    store.save(record)
    assert store.get(record.id) == record
    with pytest.raises(StorageError):
        store.save(record)
    with storage_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(LLMUsageRow)) == 1
        assert connection.scalar(select(func.count()).select_from(InvestigationRow)) == 1


def test_dashboard_groups_utc_days_and_keeps_unknowns(storage_engine: Engine) -> None:
    now = datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    store = SqlAlchemyInvestigationStore(storage_engine)
    records = [
        make_record(today - timedelta(seconds=1)),
        make_record(today - timedelta(seconds=2), tokens=2000, priced=False),
        make_record(today - timedelta(seconds=3), tokens=None),
        make_record(today - timedelta(days=40)),
    ]
    for record in records:
        store.save(record)
    dashboard = SqlAlchemyUsageReader(storage_engine).read(UsageQuery(days=7))
    assert len(dashboard.daily) == 7
    assert dashboard.totals.calls == 3
    assert dashboard.totals.reported_calls == 2
    assert dashboard.totals.priced_calls == 1
    assert dashboard.totals.total_tokens == 3000
    assert dashboard.totals.estimated_cost_usd == Decimal("0.0004")
    assert dashboard.daily[-2].calls == 3
    assert dashboard.daily[-1].calls == 0
    assert dashboard.largest[0].investigation_id == records[1].id
    by_cost = SqlAlchemyUsageReader(storage_engine).read(UsageQuery(sort="cost"))
    assert len(by_cost.largest) == 1
    by_time = SqlAlchemyUsageReader(storage_engine).read(UsageQuery(sort="duration"))
    assert len(by_time.largest) == 3


def test_old_snapshot_is_not_fabricated_as_zero_usage(storage_engine: Engine) -> None:
    record = make_record(datetime.now(UTC) - timedelta(seconds=1))
    record.report.llm_usage = None
    SqlAlchemyInvestigationStore(storage_engine).save(record)
    dashboard = SqlAlchemyUsageReader(storage_engine).read(UsageQuery())
    assert dashboard.totals.calls == 0
    assert dashboard.largest == []


def test_largest_is_bounded_to_five(storage_engine: Engine) -> None:
    now = datetime.now(UTC) - timedelta(seconds=1)
    store = SqlAlchemyInvestigationStore(storage_engine)
    for count in range(1, 8):
        store.save(make_record(now, tokens=count * 1000))
    result = SqlAlchemyUsageReader(storage_engine).read(UsageQuery())
    assert len(result.largest) == 5
    assert [item.total_tokens for item in result.largest] == [7000, 6000, 5000, 4000, 3000]
