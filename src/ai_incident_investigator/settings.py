import os
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    log_path: Path = Path("data/logs.jsonl")
    llm_enabled: bool = False
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    openai_model: str = Field(default="gpt-4.1-mini-2025-04-14", min_length=1)

    @model_validator(mode="after")
    def validate_api_key(self) -> Self:
        if self.llm_enabled and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("OPENAI_API_KEY is required when LLM_ENABLED=true")

        return self


def get_settings() -> Settings:
    raw_key = os.environ.get("OPENAI_API_KEY")

    return Settings.model_validate(
        {
            "log_path": os.environ.get("INVESTIGATOR_LOG_PATH", "data/logs.jsonl"),
            "llm_enabled": os.environ.get("LLM_ENABLED", "false"),
            "openai_api_key": SecretStr(raw_key) if raw_key else None,
            "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini-2025-04-14"),
        }
    )
