import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_incident_investigator.dependencies import get_metrics_collector
from ai_incident_investigator.investigations.reports import (
    Evidence,
    EvidenceSource,
    InvestigationReport,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.sources.metrics import MetricsCollection
from ai_incident_investigator.sources.prometheus import PrometheusCollector


@pytest.fixture
def request_model() -> InvestigationRequest:
    return InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2026, 10, 10, 10, 0, tzinfo=UTC),
        end_time=datetime(2026, 10, 10, 10, 0, 10, tzinfo=UTC),
    )


def matrix_response(values: list[list[object]], **extra: object) -> dict[str, object]:
    return {
        "status": "success",
        "data": {"resultType": "matrix", "result": [{"metric": {}, "values": values}]},
        **extra,
    }


def collect(
    request: InvestigationRequest,
    handler: Callable[[httpx.Request], httpx.Response],
) -> MetricsCollection:
    with httpx.Client(
        base_url="http://prometheus:9090",
        transport=httpx.MockTransport(handler),
    ) as client:
        return PrometheusCollector(client).collect(request)


def test_collects_three_metrics_with_reproducible_queries(
    request_model: InvestigationRequest,
) -> None:
    calls: list[httpx.Request] = []
    timestamp = request_model.start_time.timestamp()

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        query = request.url.params["query"]
        values = [0.0, 1.0] if "min(up" in query else [10.0, 12.0]
        return httpx.Response(
            200,
            json=matrix_response([[timestamp, str(values[0])], [timestamp + 5, str(values[1])]]),
        )

    result = collect(request_model, respond)

    assert result.issues == []
    assert {item.id for item in result.evidence} == {
        "metric-up",
        "metric-jvm-heap",
        "metric-http-504-counter",
    }
    assert all(item.source == EvidenceSource.METRIC for item in result.evidence)
    assert all(item.service == request_model.service for item in result.evidence)
    assert len(calls) == 3

    for call, evidence in zip(calls, result.evidence, strict=True):
        assert call.method == "GET"
        assert call.url.path == "/api/v1/query_range"
        assert datetime.fromisoformat(call.url.params["start"]) == request_model.start_time
        assert datetime.fromisoformat(call.url.params["end"]) == (
            request_model.end_time - timedelta(milliseconds=1)
        )
        assert call.url.params["step"] == "5s"
        assert call.url.params["timeout"] == "2s"
        assert call.url.params["lookback_delta"] == "15s"
        assert httpx.URL(evidence.reference).params["query"] == call.url.params["query"]
        assert evidence.start_time == request_model.start_time
        assert "min=" in evidence.summary
        assert "max=" in evidence.summary
        assert "last=" in evidence.summary
        assert "samples=2" in evidence.summary


def test_label_values_are_escaped_in_promql(request_model: InvestigationRequest) -> None:
    request_model.service = 'order"\\service\n🔥'
    request_model.environment = 'lo"cal\\'
    queries: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        queries.append(request.url.params["query"])
        return httpx.Response(
            200, json=matrix_response([[request_model.start_time.timestamp(), "1"]])
        )

    result = collect(request_model, respond)

    assert len(result.evidence) == 3
    assert all(
        f"service={json.dumps(request_model.service, ensure_ascii=False)}" in query
        for query in queries
    )
    assert all(
        f"environment={json.dumps(request_model.environment, ensure_ascii=False)}" in query
        for query in queries
    )


def test_empty_series_is_missing_data_not_zero(request_model: InvestigationRequest) -> None:
    result = collect(
        request_model,
        lambda _: httpx.Response(
            200, json={"status": "success", "data": {"resultType": "matrix", "result": []}}
        ),
    )

    assert result.evidence == []
    assert len(result.issues) == 3
    assert all("no samples" in issue for issue in result.issues)


def test_failed_query_preserves_other_metrics(request_model: InvestigationRequest) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if "jvm_memory_used_bytes" in request.url.params["query"]:
            return httpx.Response(503)

        return httpx.Response(
            200,
            json=matrix_response(
                [
                    [request_model.start_time.timestamp(), "1"],
                    [request_model.start_time.timestamp() + 5, "1"],
                ]
            ),
        )

    result = collect(request_model, respond)

    assert {item.id for item in result.evidence} == {"metric-up", "metric-http-504-counter"}
    assert len(result.issues) == 1
    assert "failed" in result.issues[0]


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_connection_failure_is_reported_as_missing_data(
    request_model: InvestigationRequest,
    error_type: type[httpx.RequestError],
) -> None:
    def disconnected(request: httpx.Request) -> httpx.Response:
        raise error_type("Prometheus is unavailable", request=request)

    result = collect(request_model, disconnected)

    assert result.evidence == []
    assert result.issues


@pytest.mark.parametrize("case", ["error", "vector", "multiple_series"])
def test_invalid_prometheus_results_are_rejected(
    request_model: InvestigationRequest,
    case: str,
) -> None:
    payload = matrix_response([[request_model.start_time.timestamp(), "1"]])

    if case == "error":
        payload = {"status": "error", "errorType": "timeout", "error": "Query timed out"}
    elif case == "vector":
        payload["data"] = {"resultType": "vector", "result": []}
    else:
        payload["data"] = {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"instance": "a"},
                    "values": [[request_model.start_time.timestamp(), "1"]],
                },
                {
                    "metric": {"instance": "b"},
                    "values": [[request_model.start_time.timestamp(), "1"]],
                },
            ],
        }

    result = collect(request_model, lambda _: httpx.Response(200, json=payload))

    assert result.evidence == []
    assert result.issues


@pytest.mark.parametrize("annotation", ["warnings", "infos"])
def test_prometheus_annotations_retain_evidence_and_report_gap(
    request_model: InvestigationRequest,
    annotation: str,
) -> None:
    result = collect(
        request_model,
        lambda _: httpx.Response(
            200,
            json=matrix_response(
                [[request_model.start_time.timestamp(), "1"]],
                **{annotation: ["Some source data was omitted."]},
            ),
        ),
    )

    assert len(result.evidence) == 3
    assert result.issues


@pytest.mark.parametrize(
    "case",
    [
        "NaN",
        "+Inf",
        "-Inf",
        "-1",
        "garbage",
        "before",
        "at_end",
        "unsorted",
        "duplicate",
        "limit",
        "up2",
    ],
)
def test_invalid_samples_are_rejected(
    request_model: InvestigationRequest,
    case: str,
) -> None:
    start = request_model.start_time.timestamp()
    special_cases: dict[str, list[list[object]]] = {
        "before": [[start - 1, "1"]],
        "at_end": [[request_model.end_time.timestamp(), "1"]],
        "unsorted": [[start + 5, "1"], [start, "1"]],
        "duplicate": [[start, "1"], [start, "1"]],
        "limit": [[start + index / 1000, "1"] for index in range(722)],
        "up2": [[start, "2"]],
    }
    values = special_cases.get(case, [[start, case]])

    result = collect(request_model, lambda _: httpx.Response(200, json=matrix_response(values)))

    expected = {"metric-jvm-heap", "metric-http-504-counter"} if case == "up2" else set()
    assert {item.id for item in result.evidence} == expected
    assert result.issues


def test_oversized_response_is_rejected(request_model: InvestigationRequest) -> None:
    payload = matrix_response(
        [[request_model.start_time.timestamp(), "1"]], padding="x" * (256 * 1024)
    )
    result = collect(
        request_model,
        lambda _: httpx.Response(200, json=payload),
    )

    assert result.evidence == []
    assert result.issues


def test_window_over_one_hour_does_not_query_prometheus(
    request_model: InvestigationRequest,
) -> None:
    request_model.end_time = request_model.start_time + timedelta(hours=1, microseconds=1)

    def unexpected_call(_: httpx.Request) -> httpx.Response:
        pytest.fail("An unsupported time window must not reach Prometheus")

    result = collect(request_model, unexpected_call)

    assert result.evidence == []
    assert result.issues


@pytest.mark.parametrize("tiny_window", [False, True])
def test_query_bounds_respect_millisecond_precision(
    request_model: InvestigationRequest,
    tiny_window: bool,
) -> None:
    original_start = request_model.start_time
    request_model.start_time += timedelta(microseconds=1)
    request_model.end_time += timedelta(microseconds=5001)

    if tiny_window:
        request_model.end_time = request_model.start_time + timedelta(microseconds=1)

    def respond(request: httpx.Request) -> httpx.Response:
        assert not tiny_window, "A window without millisecond timestamps must not reach Prometheus"

        start = datetime.fromisoformat(request.url.params["start"])
        end = datetime.fromisoformat(request.url.params["end"])

        assert start == original_start + timedelta(milliseconds=1)
        assert end == original_start + timedelta(seconds=10, milliseconds=5)

        return httpx.Response(200, json=matrix_response([[start.timestamp(), "1"]]))

    result = collect(request_model, respond)

    assert len(result.evidence) == (0 if tiny_window else 3)
    assert result.issues


def test_api_combines_logs_with_metric_evidence_and_gaps(
    app: FastAPI,
    request_model: InvestigationRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "logs.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "timestamp": request_model.start_time.isoformat(),
                "service": request_model.service,
                "environment": request_model.environment,
                "level": "ERROR",
                "message": "Payment request timed out.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INVESTIGATOR_LOG_PATH", str(log_path))

    metric = Evidence(
        id="metric-up",
        source=EvidenceSource.METRIC,
        service=request_model.service,
        summary="up: min=1; max=1; last=1; samples=1",
        reference="http://prometheus:9090/api/v1/query_range",
        start_time=request_model.start_time,
    )

    class FakeCollector:
        def collect(self, request: InvestigationRequest) -> MetricsCollection:
            assert request == request_model
            return MetricsCollection(evidence=[metric], issues=["HTTP counter samples missing."])

    app.dependency_overrides[get_metrics_collector] = FakeCollector

    try:
        with TestClient(app) as client:
            response = client.post("/investigations", json=request_model.model_dump(mode="json"))
    finally:
        app.dependency_overrides.pop(get_metrics_collector, None)

    assert response.status_code == 200

    report = InvestigationReport.model_validate(response.json())

    assert {item.source for item in report.evidence} == {EvidenceSource.LOG, EvidenceSource.METRIC}
    assert "HTTP counter samples missing." in report.missing_data
    assert not any("metrics source is not connected" in issue for issue in report.missing_data)
    assert report.analysis_status == "not_requested"
    assert report.findings == []
    assert report.hypotheses == []
