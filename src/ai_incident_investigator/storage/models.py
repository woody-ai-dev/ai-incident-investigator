from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class InvestigationRow(Base):
    __tablename__ = "investigations"
    __table_args__ = (
        CheckConstraint("duration_ms >= 0", name="ck_investigations_duration_nonnegative"),
        CheckConstraint("schema_version = 1", name="ck_investigations_schema_version"),
        Index("ix_investigations_created_id", "created_at", "id"),
        Index(
            "ix_investigations_service_environment_created", "service", "environment", "created_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    environment: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    configured_model: Mapped[str | None] = mapped_column(Text)
    prompt_sha256: Mapped[str | None] = mapped_column(String(64))
    request_payload: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    report_payload: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )


class LLMUsageRow(Base):
    __tablename__ = "llm_usage"
    __table_args__ = (
        CheckConstraint("duration_ms >= 0", name="ck_llm_usage_duration"),
        CheckConstraint(
            "estimated_cost_usd IS NULL OR estimated_cost_usd >= 0", name="ck_llm_usage_cost"
        ),
        CheckConstraint(
            "(input_tokens IS NULL AND cached_input_tokens IS NULL "
            "AND output_tokens IS NULL AND total_tokens IS NULL) OR "
            "(input_tokens IS NOT NULL AND cached_input_tokens IS NOT NULL "
            "AND output_tokens IS NOT NULL AND total_tokens IS NOT NULL "
            "AND input_tokens >= 0 AND cached_input_tokens >= 0 "
            "AND cached_input_tokens <= input_tokens AND output_tokens >= 0 "
            "AND total_tokens = input_tokens + output_tokens)",
            name="ck_llm_usage_tokens",
        ),
        Index("ix_llm_usage_started_id", "started_at", "investigation_id"),
    )

    investigation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("investigations.id", ondelete="CASCADE"), primary_key=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cached_input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
