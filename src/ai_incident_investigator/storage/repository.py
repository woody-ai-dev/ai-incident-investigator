from datetime import UTC
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_incident_investigator.investigations.ports import StorageError
from ai_incident_investigator.investigations.records import StoredInvestigation
from ai_incident_investigator.storage.models import InvestigationRow


class SqlAlchemyInvestigationStore:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, class_=Session)

    def check_ready(self) -> None:
        try:
            with self._sessions() as session:
                session.execute(select(InvestigationRow).limit(0))
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
        except SQLAlchemyError as exc:
            raise StorageError("Investigation could not be saved") from exc

    def get(self, investigation_id: UUID) -> StoredInvestigation | None:
        try:
            with self._sessions() as session:
                row = session.get(InvestigationRow, investigation_id)
                if row is None:
                    return None

                # SQLite tests return naive datetimes; stored timestamps are always UTC.
                created_at = row.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                else:
                    created_at = created_at.astimezone(UTC)

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
