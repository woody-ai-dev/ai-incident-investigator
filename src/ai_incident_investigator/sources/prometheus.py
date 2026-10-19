import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import httpx
from pydantic import BaseModel, Field, FiniteFloat

from ai_incident_investigator.investigations.metric_catalog import (
    HTTP_504_COUNTER,
    JVM_HEAP_USAGE,
    SCRAPE_SUCCESS,
    MetricDefinition,
)
from ai_incident_investigator.investigations.reports import Evidence, EvidenceSource
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.sources.metrics import MetricsCollection

STEP_SECONDS = 5
MAX_WINDOW = timedelta(hours=1)
MAX_POINTS = 721
MAX_RESPONSE_BYTES = 256 * 1024


class RangeSeries(BaseModel):
    values: list[tuple[FiniteFloat, str]] = Field(max_length=MAX_POINTS)


class RangeData(BaseModel):
    result_type: Literal["matrix"] = Field(alias="resultType")
    result: list[RangeSeries] = Field(max_length=1)


class RangeResponse(BaseModel):
    status: Literal["success"]
    data: RangeData
    warnings: list[str] = Field(default_factory=list)
    infos: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class MetricQuery:
    definition: MetricDefinition
    expression: str

    @property
    def key(self) -> str:
        return self.definition.key

    @property
    def description(self) -> str:
        return self.definition.description


def build_queries(request: InvestigationRequest) -> tuple[MetricQuery, ...]:
    labels = (
        f"service={json.dumps(request.service, ensure_ascii=False)},"
        f"environment={json.dumps(request.environment, ensure_ascii=False)}"
    )

    return (
        MetricQuery(
            definition=SCRAPE_SUCCESS,
            expression=f"min(up{{{labels}}})",
        ),
        MetricQuery(
            definition=JVM_HEAP_USAGE,
            expression=f'sum(jvm_memory_used_bytes{{{labels},area="heap"}})',
        ),
        MetricQuery(
            definition=HTTP_504_COUNTER,
            expression=(
                f"sum(http_server_requests_seconds_count{{{labels},"
                'uri="/api/v1/orders",method="POST",status="504"})'
            ),
        ),
    )


class PrometheusCollector:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def collect(self, request: InvestigationRequest) -> MetricsCollection:
        result = MetricsCollection()
        window = request.end_time - request.start_time

        if window > MAX_WINDOW:
            result.issues.append("Prometheus collection skipped: time window exceeds one hour.")
            return result

        query_start = request.start_time + timedelta(
            microseconds=(-request.start_time.microsecond) % 1000
        )
        query_end = request.end_time - timedelta(microseconds=1)
        query_end = query_end.replace(microsecond=query_end.microsecond // 1000 * 1000)

        if query_start > query_end:
            result.issues.append(
                "Prometheus collection skipped: window contains no millisecond evaluation point."
            )
            return result

        expected_points = int((query_end - query_start).total_seconds() // STEP_SECONDS) + 1

        for query in build_queries(request):
            try:
                body, reference = self._query(query.expression, query_start, query_end)
                samples = self._samples(body, query.key, request)

                if body.warnings or body.infos:
                    result.issues.append(
                        f"Prometheus returned annotations for {query.key}; "
                        "query results may be incomplete."
                    )

                if not samples:
                    result.issues.append(
                        f"Prometheus returned no samples for {query.key}; "
                        "absence of data does not mean zero."
                    )
                    continue

                if len(samples) < expected_points:
                    result.issues.append(
                        f"Prometheus {query.key} returned {len(samples)} of "
                        f"{expected_points} expected evaluation samples; coverage is incomplete."
                    )

                result.evidence.append(
                    Evidence(
                        id=query.definition.evidence_id,
                        source=EvidenceSource.METRIC,
                        service=request.service,
                        summary=(
                            f"{query.description}. Evaluation samples={len(samples)}, "
                            f"min={min(samples):g}, max={max(samples):g}, last={samples[-1]:g}; "
                            "step=5s, lookback=15s. Evaluation times are not scrape times."
                        ),
                        reference=reference,
                        start_time=request.start_time,
                        end_time=request.end_time,
                    )
                )
            except (httpx.HTTPError, ValueError):
                result.issues.append(
                    f"Prometheus query failed for {query.key}; metric coverage is incomplete."
                )

        return result

    def _query(
        self,
        expression: str,
        query_start: datetime,
        query_end: datetime,
    ) -> tuple[RangeResponse, str]:
        params = {
            "query": expression,
            "start": query_start.isoformat(),
            "end": query_end.isoformat(),
            "step": "5s",
            "timeout": "2s",
            "lookback_delta": "15s",
        }
        reference = str(self.client.build_request("GET", "api/v1/query_range", params=params).url)

        with self.client.stream("GET", "api/v1/query_range", params=params) as response:
            response.raise_for_status()
            payload = bytearray()

            for chunk in response.iter_bytes(chunk_size=8192):
                if len(payload) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ValueError("Prometheus response exceeds the byte limit")
                payload.extend(chunk)

        return RangeResponse.model_validate_json(payload), reference

    @staticmethod
    def _samples(
        body: RangeResponse,
        key: str,
        request: InvestigationRequest,
    ) -> list[float]:
        if not body.data.result:
            return []

        samples: list[float] = []
        previous_timestamp = -math.inf

        for timestamp, raw_value in body.data.result[0].values:
            value = float(raw_value)

            if not request.start_time.timestamp() <= timestamp < request.end_time.timestamp():
                raise ValueError("Metric evaluation timestamp is outside the requested window")
            if timestamp <= previous_timestamp:
                raise ValueError("Metric evaluation timestamps must increase")
            if not math.isfinite(value) or value < 0:
                raise ValueError("Metric value must be finite and non-negative")
            if key == SCRAPE_SUCCESS.key and value not in (0.0, 1.0):
                raise ValueError("Scrape availability must be zero or one")

            previous_timestamp = timestamp
            samples.append(value)

        return samples
