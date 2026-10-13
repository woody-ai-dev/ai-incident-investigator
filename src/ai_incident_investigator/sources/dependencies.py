from collections.abc import Iterator
from typing import Annotated

import httpx
from fastapi import Depends

from ai_incident_investigator.settings import Settings, get_settings
from ai_incident_investigator.sources.actuator import HttpActuatorCollector
from ai_incident_investigator.sources.context import ActuatorCollector
from ai_incident_investigator.sources.metrics import MetricsCollector
from ai_incident_investigator.sources.prometheus import PrometheusCollector


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
