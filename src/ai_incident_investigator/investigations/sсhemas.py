from datetime import UTC, datetime
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class InvestigationRequest(BaseModel):
    """Identify the service and time window to investigate."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    service: str = Field(min_length=1, max_length=100)
    environment: str = Field(min_length=1, max_length=100)
    start_time: AwareDatetime
    end_time: AwareDatetime
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def parse_timestamp(cls, value: object) -> datetime:
        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            return datetime.fromisoformat(value)

        raise ValueError("timestamp must be an ISO 8601 string or a date time object")

    @field_validator("start_time", "end_time")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")

        return self
