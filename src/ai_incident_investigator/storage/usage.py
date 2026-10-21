from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import BigInteger, Engine, cast, func, select
from sqlalchemy.exc import SQLAlchemyError

from ai_incident_investigator.investigations.ports import StorageError
from ai_incident_investigator.storage.models import InvestigationRow, LLMUsageRow
from ai_incident_investigator.usage.models import (
    LargeAnalysis,
    UsageDashboard,
    UsageDay,
    UsageQuery,
    UsageTotals,
)


class SqlAlchemyUsageReader:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def read(self, query: UsageQuery) -> UsageDashboard:
        end = datetime.now(UTC)
        start = end.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=query.days - 1
        )
        table = LLMUsageRow
        day = func.date(
            func.timezone("UTC", table.started_at)
            if self._engine.dialect.name == "postgresql"
            else table.started_at
        )
        window = (table.started_at >= start, table.started_at < end)
        count_fields = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
        grouped = (
            select(
                day.label("day"),
                func.count().label("calls"),
                func.count(table.total_tokens).label("reported_calls"),
                func.count(table.estimated_cost_usd).label("priced_calls"),
                *(
                    cast(func.coalesce(func.sum(getattr(table, name)), 0), BigInteger).label(name)
                    for name in count_fields
                ),
                func.coalesce(func.sum(table.estimated_cost_usd), 0).label("estimated_cost_usd"),
            )
            .where(*window)
            .group_by(day)
        )
        ranking = {
            "tokens": table.total_tokens,
            "cost": table.estimated_cost_usd,
            "duration": table.duration_ms,
        }[query.sort]
        largest = (
            select(
                table.investigation_id,
                InvestigationRow.service,
                InvestigationRow.environment,
                table.started_at,
                table.duration_ms,
                table.total_tokens,
                table.estimated_cost_usd,
            )
            .join(InvestigationRow, InvestigationRow.id == table.investigation_id)
            .where(*window, ranking.is_not(None))
            .order_by(ranking.desc(), table.started_at.desc(), table.investigation_id.desc())
            .limit(5)
        )
        try:
            with self._engine.connect() as connection:
                if self._engine.dialect.name == "postgresql":
                    connection = connection.execution_options(isolation_level="REPEATABLE READ")
                with connection.begin():
                    by_day = {
                        str(row["day"]): UsageDay.model_validate(dict(row))
                        for row in connection.execute(grouped).mappings()
                    }
                    leaders = [
                        LargeAnalysis.model_validate(
                            {
                                **row,
                                "started_at": row["started_at"].replace(tzinfo=UTC)
                                if row["started_at"].tzinfo is None
                                else row["started_at"],
                            }
                        )
                        for row in connection.execute(largest).mappings()
                    ]
            days = [start.date() + timedelta(days=index) for index in range(query.days)]
            daily = [by_day.get(day.isoformat(), UsageDay(day=day)) for day in days]
            totals = UsageTotals.model_validate(
                {
                    name: sum(
                        (getattr(item, name) for item in daily),
                        Decimal(0) if name == "estimated_cost_usd" else 0,
                    )
                    for name in UsageTotals.model_fields
                }
            )
            return UsageDashboard(
                generated_at=end,
                start_time=start,
                end_time=end,
                totals=totals,
                daily=daily,
                largest=leaders,
            )
        except (SQLAlchemyError, ValidationError) as exc:
            raise StorageError("Usage statistics could not be loaded") from exc
