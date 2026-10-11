from collections.abc import Iterator
from typing import Annotated

import httpx
from fastapi import Depends

from ai_incident_investigator.settings import Settings, get_settings
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
