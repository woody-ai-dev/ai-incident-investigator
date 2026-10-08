from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from openai import OpenAI

from ai_incident_investigator.investigations.analysis import Analyzer
from ai_incident_investigator.llm.openai_client import OpenAIAnalyzer
from ai_incident_investigator.settings import Settings, get_settings


def get_analyzer(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[Analyzer | None]:
    if not settings.llm_enabled:
        yield None
        return

    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is required")

    with OpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url="https://api.openai.com/v1",
        timeout=20.0,
        max_retries=1,
    ) as client:
        yield OpenAIAnalyzer(client, settings.openai_model)
