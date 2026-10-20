import os
from pathlib import Path
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def validate_database_url(value: SecretStr) -> SecretStr:
    try:
        url = make_url(value.get_secret_value())
    except (ArgumentError, ValueError):
        raise ValueError("DATABASE_URL must be a valid PostgreSQL URL") from None

    if url.drivername != "postgresql+psycopg" or not url.host or not url.database:
        raise ValueError("DATABASE_URL must use postgresql+psycopg and include host and database")

    return value


class ActuatorTarget(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    base_url: HttpUrl
    service: str = Field(min_length=1, max_length=100)
    environment: str = Field(min_length=1, max_length=100)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: HttpUrl) -> HttpUrl:
        if (
            len(str(value)) > 512
            or value.username is not None
            or value.password is not None
            or value.query is not None
            or value.fragment is not None
        ):
            raise ValueError("ACTUATOR_URL must be a base URL without credentials or query data")

        return value


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    log_path: Path = Path("data/logs.jsonl")
    prometheus_url: HttpUrl | None = None
    actuator_target: ActuatorTarget | None = None
    database_url: SecretStr | None = Field(default=None, repr=False, exclude=True)

    llm_enabled: bool = False
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    openai_model: str = Field(
        default="gpt-4.1-mini-2025-04-14",
        min_length=1,
    )

    @field_validator("database_url")
    @classmethod
    def validate_storage_url(cls, value: SecretStr | None) -> SecretStr | None:
        return validate_database_url(value) if value is not None else None

    @field_validator("prometheus_url")
    @classmethod
    def validate_prometheus_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and (
            len(str(value)) > 512
            or value.username is not None
            or value.password is not None
            or value.query is not None
            or value.fragment is not None
        ):
            raise ValueError("PROMETHEUS_URL must be a base URL without credentials or query data")

        return value

    @model_validator(mode="after")
    def validate_api_key(self) -> Self:
        if self.llm_enabled and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("OPENAI_API_KEY is required when LLM_ENABLED=true")

        return self


def get_settings() -> Settings:
    raw_key = os.environ.get("OPENAI_API_KEY")
    raw_database_url = os.environ.get("DATABASE_URL")

    actuator_target = {
        "base_url": os.environ.get("ACTUATOR_URL") or None,
        "service": os.environ.get("ACTUATOR_SERVICE") or None,
        "environment": os.environ.get("ACTUATOR_ENVIRONMENT") or None,
    }

    return Settings.model_validate(
        {
            "log_path": os.environ.get(
                "INVESTIGATOR_LOG_PATH",
                "data/logs.jsonl",
            ),
            "prometheus_url": os.environ.get("PROMETHEUS_URL") or None,
            "database_url": SecretStr(raw_database_url) if raw_database_url else None,
            "actuator_target": (actuator_target if any(actuator_target.values()) else None),
            "llm_enabled": os.environ.get("LLM_ENABLED", "false"),
            "openai_api_key": SecretStr(raw_key) if raw_key else None,
            "openai_model": os.environ.get(
                "OPENAI_MODEL",
                "gpt-4.1-mini-2025-04-14",
            ),
        }
    )
