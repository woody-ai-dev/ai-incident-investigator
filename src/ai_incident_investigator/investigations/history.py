"""Read models and bounded queries for saved investigation history."""

import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_incident_investigator.investigations.reports import ReportModel


class HistoryCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    created_at: AwareDatetime
    id: UUID

    def encode(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> Self:
        try:
            raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
            return cls.model_validate_json(raw)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid history cursor") from exc


class InvestigationQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    service: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    environment: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    created_from: AwareDatetime | None = None
    created_until: AwareDatetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: Annotated[str, Field(min_length=1, max_length=512)] | None = None

    @field_validator("created_from", "created_until")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None

    @field_validator("cursor")
    @classmethod
    def validate_cursor(cls, value: str | None) -> str | None:
        if value is not None:
            HistoryCursor.decode(value)
        return value

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if (
            self.created_from is not None
            and self.created_until is not None
            and self.created_until <= self.created_from
        ):
            raise ValueError("created_until must be after created_from")
        return self


class InvestigationSummary(ReportModel):
    id: UUID
    created_at: AwareDatetime
    service: Annotated[str, Field(min_length=1, max_length=100)]
    environment: Annotated[str, Field(min_length=1, max_length=100)]
    duration_ms: int = Field(ge=0)
    configured_model: str | None
    analysis_status: Literal["not_requested", "skipped", "completed", "failed"]
    summary: Annotated[str, Field(min_length=1, max_length=4000)]


class InvestigationPage(ReportModel):
    items: list[InvestigationSummary]
    next_cursor: str | None = None
