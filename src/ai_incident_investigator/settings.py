import os
from pathlib import Path

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    log_path: Path


def get_settings() -> Settings:
    return Settings(log_path=Path(os.environ.get("INVESTIGATOR_LOG_PATH", "data/logs.jsonl")))
