from collections.abc import Iterator
from hashlib import sha256
from typing import Annotated, cast

import httpx
from fastapi import Depends, Request
from openai import OpenAI

from ai_incident_investigator.investigations.analysis import Analyzer
from ai_incident_investigator.investigations.ports import InvestigationStore
from ai_incident_investigator.investigations.workflow import AnalysisConfiguration
from ai_incident_investigator.llm.openai_client import OpenAIAnalyzer
from ai_incident_investigator.llm.prompts import SYSTEM_PROMPT
from ai_incident_investigator.settings import Settings, get_settings
from ai_incident_investigator.sources.actuator import HttpActuatorCollector
from ai_incident_investigator.sources.context import ActuatorCollector
from ai_incident_investigator.sources.metrics import MetricsCollector
from ai_incident_investigator.sources.prometheus import PrometheusCollector


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
        max_retries=0,
    ) as client:
        yield OpenAIAnalyzer(client, settings.openai_model)


def get_metrics_collector(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[MetricsCollector | None]:
    if settings.prometheus_url is None:
        yield None
        return

    with httpx.Client(
        base_url=str(settings.prometheus_url),
        timeout=httpx.Timeout(3.0, connect=1.0),
        trust_env=False,
        follow_redirects=False,
        headers={"Accept": "application/json"},
    ) as client:
        yield PrometheusCollector(client)


def get_actuator_collector(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[ActuatorCollector | None]:
    if settings.actuator_target is None:
        yield None
        return

    target = settings.actuator_target

    with httpx.Client(
        base_url=str(target.base_url).rstrip("/") + "/",
        timeout=httpx.Timeout(3.0, connect=1.0),
        trust_env=False,
        follow_redirects=False,
        headers={"Accept": "application/json"},
    ) as client:
        yield HttpActuatorCollector(client, target)


def get_investigation_store(request: Request) -> InvestigationStore | None:
    return cast(InvestigationStore | None, getattr(request.app.state, "investigation_store", None))


def get_analysis_configuration(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalysisConfiguration:
    if not settings.llm_enabled:
        return AnalysisConfiguration()
    return AnalysisConfiguration(
        configured_model=settings.openai_model,
        prompt_sha256=sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
    )
