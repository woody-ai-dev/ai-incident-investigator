from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ai_incident_investigator.investigations.metric_catalog import (
    HTTP_504_COUNTER,
    JVM_HEAP_USAGE,
    METRIC_DEFINITIONS,
    SCRAPE_SUCCESS,
    MetricKind,
    metric_definition,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.sources.prometheus import PrometheusCollector, build_queries


@pytest.fixture
def request_model() -> InvestigationRequest:
    start = datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
    return InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=start,
        end_time=start + timedelta(seconds=10),
    )


def test_catalogue_resolves_unique_typed_definitions() -> None:
    assert METRIC_DEFINITIONS == (SCRAPE_SUCCESS, JVM_HEAP_USAGE, HTTP_504_COUNTER)
    assert {definition.evidence_id for definition in METRIC_DEFINITIONS} == {
        "metric-up",
        "metric-jvm-heap",
        "metric-http-504-counter",
    }
    assert {definition.kind for definition in METRIC_DEFINITIONS} == set(MetricKind)
    assert SCRAPE_SUCCESS.kind is MetricKind.SCRAPE_SUCCESS
    assert JVM_HEAP_USAGE.kind is MetricKind.JVM_HEAP_USAGE
    assert HTTP_504_COUNTER.kind is MetricKind.CUMULATIVE_HTTP_COUNTER

    for definition in METRIC_DEFINITIONS:
        assert metric_definition(definition.evidence_id) is definition
        assert definition.supported_observation
        assert isinstance(definition.limitations, tuple)
        assert definition.limitations


@pytest.mark.parametrize(
    "evidence_id",
    [
        "",
        "up",
        "metric-unknown",
        "metric-UP",
        "metric-up-extra",
        " metric-up",
        "metric-up ",
        "Minimum scrape availability across observed targets (0 or 1)",
        "Aggregated JVM heap usage in bytes. Evaluation samples=2, min=1, max=2, last=2",
    ],
)
def test_unknown_metric_identifiers_do_not_infer_semantics(evidence_id: str) -> None:
    assert metric_definition(evidence_id) is None


def test_producer_queries_use_catalogue_and_preserve_promql(
    request_model: InvestigationRequest,
) -> None:
    queries = build_queries(request_model)

    assert tuple(query.definition for query in queries) == METRIC_DEFINITIONS
    assert tuple(query.expression for query in queries) == (
        'min(up{service="order-service",environment="local"})',
        'sum(jvm_memory_used_bytes{service="order-service",environment="local",area="heap"})',
        'sum(http_server_requests_seconds_count{service="order-service",environment="local",'
        'uri="/api/v1/orders",method="POST",status="504"})',
    )

    for query in queries:
        assert query.definition is metric_definition(query.definition.evidence_id)
        assert query.key == query.definition.key
        assert query.description == query.definition.description


def test_producer_evidence_uses_catalogue_without_changing_numeric_summaries(
    request_model: InvestigationRequest,
) -> None:
    timestamp = request_model.start_time.timestamp()
    queries = build_queries(request_model)
    values_by_query = {
        queries[0].expression: ("0", "1"),
        queries[1].expression: ("100", "120"),
        queries[2].expression: ("45", "40"),
    }

    def respond(request: httpx.Request) -> httpx.Response:
        first, last = values_by_query[request.url.params["query"]]
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [{"values": [[timestamp, first], [timestamp + 5, last]]}],
                },
            },
        )

    with httpx.Client(
        base_url="http://prometheus:9090",
        transport=httpx.MockTransport(respond),
    ) as client:
        result = PrometheusCollector(client).collect(request_model)

    assert result.issues == []
    expected_observations = (
        "Evaluation samples=2, min=0, max=1, last=1",
        "Evaluation samples=2, min=100, max=120, last=120",
        "Evaluation samples=2, min=40, max=45, last=40",
    )
    expected_descriptions = (
        "Minimum scrape availability across observed targets (0 or 1)",
        "Aggregated JVM heap usage in bytes",
        "Aggregated cumulative HTTP 504 counter for POST /api/v1/orders; "
        "may reset; not the number of errors in the investigation window",
    )

    for evidence, definition, description, observation in zip(
        result.evidence,
        METRIC_DEFINITIONS,
        expected_descriptions,
        expected_observations,
        strict=True,
    ):
        assert evidence.id == definition.evidence_id
        assert metric_definition(evidence.id) is definition
        assert definition.description == description
        assert evidence.summary == (
            f"{description}. {observation}; "
            "step=5s, lookback=15s. Evaluation times are not scrape times."
        )
