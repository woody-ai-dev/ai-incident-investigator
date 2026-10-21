from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Engine, and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_incident_investigator.investigations.history import (
    HistoryCursor,
    InvestigationPage,
    InvestigationQuery,
    InvestigationSummary,
)
from ai_incident_investigator.investigations.ports import StorageError
from ai_incident_investigator.investigations.records import StoredInvestigation
from ai_incident_investigator.storage.models import InvestigationRow, LLMUsageRow


class SqlAlchemyInvestigationStore:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, class_=Session)

    def check_ready(self) -> None:
        try:
            with self._sessions() as session:
                session.execute(select(InvestigationRow).limit(0))
                session.execute(select(LLMUsageRow).limit(0))
        except SQLAlchemyError as exc:
            raise StorageError("Investigation storage is unavailable or not migrated") from exc

    def save(self, record: StoredInvestigation) -> None:
        row = InvestigationRow(
            id=record.id,
            created_at=record.created_at.astimezone(UTC),
            schema_version=record.schema_version,
            service=record.request.service,
            environment=record.request.environment,
            duration_ms=record.duration_ms,
            configured_model=record.configured_model,
            prompt_sha256=record.prompt_sha256,
            request_payload=record.request.model_dump(mode="json"),
            report_payload=record.report.model_dump(mode="json"),
        )

        try:
            with self._sessions.begin() as session:
                session.add(row)
                if record.report.llm_usage is not None:
                    session.flush()
                    usage = record.report.llm_usage
                    tokens = usage.tokens
                    session.add(
                        LLMUsageRow(
                            investigation_id=record.id,
                            started_at=usage.started_at.astimezone(UTC),
                            duration_ms=usage.duration_ms,
                            input_tokens=tokens.input_tokens if tokens is not None else None,
                            cached_input_tokens=tokens.cached_input_tokens
                            if tokens is not None
                            else None,
                            output_tokens=tokens.output_tokens if tokens is not None else None,
                            total_tokens=tokens.total_tokens if tokens is not None else None,
                            estimated_cost_usd=usage.estimated_cost_usd,
                        )
                    )
        except SQLAlchemyError as exc:
            raise StorageError("Investigation could not be saved") from exc

    def get(self, investigation_id: UUID) -> StoredInvestigation | None:
        try:
            with self._sessions() as session:
                row = session.get(InvestigationRow, investigation_id)
                if row is None:
                    return None

                # SQLite tests return naive datetimes; stored timestamps are always UTC.
                created_at = _utc(row.created_at)

                return StoredInvestigation.model_validate(
                    {
                        "id": row.id,
                        "created_at": created_at,
                        "schema_version": row.schema_version,
                        "duration_ms": row.duration_ms,
                        "configured_model": row.configured_model,
                        "prompt_sha256": row.prompt_sha256,
                        "request": row.request_payload,
                        "report": row.report_payload,
                    }
                )
        except (SQLAlchemyError, ValidationError) as exc:
            raise StorageError("Investigation could not be loaded") from exc

    def list_investigations(self, query: InvestigationQuery) -> InvestigationPage:
        # Project small fields only: evidence and full report JSON never enter the list response.
        statement = select(
            InvestigationRow.id,
            InvestigationRow.created_at,
            InvestigationRow.service,
            InvestigationRow.environment,
            InvestigationRow.duration_ms,
            InvestigationRow.configured_model,
            InvestigationRow.report_payload["analysis_status"].as_string().label("analysis_status"),
            InvestigationRow.report_payload["summary"].as_string().label("summary"),
        )
        if query.service is not None:
            statement = statement.where(InvestigationRow.service == query.service)
        if query.environment is not None:
            statement = statement.where(InvestigationRow.environment == query.environment)
        if query.created_from is not None:
            statement = statement.where(InvestigationRow.created_at >= query.created_from)
        if query.created_until is not None:
            statement = statement.where(InvestigationRow.created_at < query.created_until)
        if query.cursor is not None:
            cursor = HistoryCursor.decode(query.cursor)
            statement = statement.where(
                or_(
                    InvestigationRow.created_at < cursor.created_at,
                    and_(
                        InvestigationRow.created_at == cursor.created_at,
                        InvestigationRow.id < cursor.id,
                    ),
                )
            )
        statement = statement.order_by(
            InvestigationRow.created_at.desc(), InvestigationRow.id.desc()
        ).limit(query.limit + 1)
        try:
            with self._sessions() as session:
                rows = session.execute(statement).mappings().all()
                items = [
                    InvestigationSummary.model_validate(
                        {**row, "created_at": _utc(row["created_at"])}
                    )
                    for row in rows[: query.limit]
                ]
            next_cursor = None
            if len(rows) > query.limit:
                last = items[-1]
                next_cursor = HistoryCursor(created_at=last.created_at, id=last.id).encode()
            return InvestigationPage(items=items, next_cursor=next_cursor)
        except (SQLAlchemyError, ValidationError) as exc:
            raise StorageError("Investigation history could not be loaded") from exc


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
