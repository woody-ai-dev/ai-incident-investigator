import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_incident_investigator.investigations.reports import (
    Evidence,
    EvidenceSource,
    InvestigationReport,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.main import app
from ai_incident_investigator.settings import ActuatorTarget
from ai_incident_investigator.sources.actuator import (
    MAX_RESPONSE_BYTES,
    HttpActuatorCollector,
)
from ai_incident_investigator.sources.context import ActuatorCollection
from ai_incident_investigator.sources.dependencies import (
    get_actuator_collector,
    get_metrics_collector,
)
from ai_incident_investigator.sources.metrics import MetricsCollection

BASE_URL = "http://order-service:8081/actuator/"

APP_INFO = {
    "name": "order-service",
    "environment": "local",
    "version": "0.1.0",
}


@pytest.fixture
def request_model() -> InvestigationRequest:
    return InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2020, 1, 1, 10, tzinfo=UTC),
        end_time=datetime(2020, 1, 1, 11, tzinfo=UTC),
    )


def target() -> ActuatorTarget:
    return ActuatorTarget.model_validate(
        {
            "base_url": BASE_URL,
            "service": "order-service",
            "environment": "local",
        }
    )


def collect(
    request: InvestigationRequest,
    handler: Callable[[httpx.Request], httpx.Response],
) -> ActuatorCollection:
    with httpx.Client(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    ) as client:
        return HttpActuatorCollector(client, target()).collect(request)


def test_snapshots_are_sanitized_and_keep_actual_observation_times(
    request_model: InvestigationRequest,
) -> None:
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)

        if request.url.path.endswith("/info"):
            return httpx.Response(
                200,
                json={
                    "app": {**APP_INFO, "token": "private-token"},
                    "env": "private-env",
                },
            )

        return httpx.Response(
            200,
            json={
                "status": "UP",
                "components": {"database": "private-host"},
            },
        )

    before = datetime.now(UTC)
    result = collect(request_model, respond)
    after = datetime.now(UTC)

    assert [call.url.path for call in calls] == [
        "/actuator/info",
        "/actuator/health",
    ]
    assert all(call.method == "GET" for call in calls)

    assert [item.id for item in result.evidence] == [
        "actuator-info",
        "actuator-health",
    ]
    assert all(item.source == EvidenceSource.ACTUATOR for item in result.evidence)
    assert all(item.service == request_model.service for item in result.evidence)
    assert all(before <= item.start_time <= after for item in result.evidence)
    assert all(item.end_time is None for item in result.evidence)

    assert [item.reference for item in result.evidence] == [
        BASE_URL + "info",
        BASE_URL + "health",
    ]

    assert "name=order-service, environment=local, version=0.1.0" in result.evidence[0].summary
    assert "status=UP" in result.evidence[1].summary

    assert "private-" not in result.model_dump_json()
    assert any("not historical" in issue for issue in result.issues)
    assert any("outside" in issue for issue in result.issues)


@pytest.mark.parametrize(
    ("status_code", "health_status", "accepted"),
    [
        (200, "UP", True),
        (503, "DOWN", True),
        (503, "OUT_OF_SERVICE", True),
        (503, "UP", False),
    ],
)
def test_health_503_can_be_valid_evidence(
    request_model: InvestigationRequest,
    status_code: int,
    health_status: str,
    accepted: bool,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/info"):
            return httpx.Response(200, json={"app": APP_INFO})

        return httpx.Response(
            status_code,
            json={"status": health_status},
        )

    result = collect(request_model, respond)

    assert len(result.evidence) == (2 if accepted else 1)

    if accepted:
        assert f"status={health_status}" in result.evidence[1].summary
        assert f"HTTP {status_code}" in result.evidence[1].summary
    else:
        assert any("health could not" in issue for issue in result.issues)


@pytest.mark.parametrize("field", ["service", "environment"])
def test_unconfigured_request_makes_no_http_calls(
    request_model: InvestigationRequest,
    field: str,
) -> None:
    request_model = request_model.model_copy(update={field: "different"})

    def unexpected_request(_: httpx.Request) -> httpx.Response:
        pytest.fail("A different service/environment must not contact this target")

    result = collect(request_model, unexpected_request)

    assert result.evidence == []
    assert any("no target is configured" in issue for issue in result.issues)


@pytest.mark.parametrize("field", ["name", "environment"])
def test_wrong_reported_identity_rejects_context_and_skips_health(
    request_model: InvestigationRequest,
    field: str,
) -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)

        return httpx.Response(
            200,
            json={"app": {**APP_INFO, field: "different"}},
        )

    result = collect(request_model, respond)

    assert calls == ["/actuator/info"]
    assert result.evidence == []
    assert any("identity does not match" in issue for issue in result.issues)


@pytest.mark.parametrize(
    "failure",
    ["timeout", "malformed", "missing-app", "oversize", "401", "302"],
)
def test_unusable_info_skips_health(
    request_model: InvestigationRequest,
    failure: str,
) -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)

        if failure == "timeout":
            raise httpx.ReadTimeout("Timed out", request=request)

        if failure == "malformed":
            return httpx.Response(200, content=b"not JSON")

        if failure == "missing-app":
            return httpx.Response(200, json={})

        if failure == "oversize":
            return httpx.Response(
                200,
                json={
                    "app": APP_INFO,
                    "padding": "x" * MAX_RESPONSE_BYTES,
                },
            )

        return httpx.Response(
            int(failure),
            headers={"Location": "http://different/actuator/info"},
        )

    result = collect(request_model, respond)

    assert calls == ["/actuator/info"]
    assert result.evidence == []
    assert any("identity could not be verified" in issue for issue in result.issues)


@pytest.mark.parametrize(
    "failure",
    ["timeout", "oversize", "invalid-status"],
)
def test_unusable_health_preserves_valid_info(
    request_model: InvestigationRequest,
    failure: str,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/info"):
            return httpx.Response(200, json={"app": APP_INFO})

        if failure == "timeout":
            raise httpx.ReadTimeout("Timed out", request=request)

        if failure == "oversize":
            return httpx.Response(
                200,
                json={
                    "status": "UP",
                    "padding": "x" * MAX_RESPONSE_BYTES,
                },
            )

        return httpx.Response(
            200,
            json={"status": "unexpected"},
        )

    result = collect(request_model, respond)

    assert [item.id for item in result.evidence] == ["actuator-info"]
    assert any("health could not" in issue for issue in result.issues)
    assert any("not historical" in issue for issue in result.issues)


class FakeMetricsCollector:
    def collect(
        self,
        request: InvestigationRequest,
    ) -> MetricsCollection:
        return MetricsCollection(
            evidence=[
                Evidence(
                    id="metric-up",
                    source=EvidenceSource.METRIC,
                    service=request.service,
                    summary="up=1",
                    reference="http://prometheus:9090/api/v1/query_range",
                    start_time=request.start_time,
                    end_time=request.end_time,
                )
            ]
        )


@pytest.mark.parametrize("actuator_available", [True, False])
def test_api_preserves_other_sources_when_actuator_is_unavailable(
    request_model: InvestigationRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    actuator_available: bool,
) -> None:
    log_path = tmp_path / "logs.jsonl"

    log_path.write_text(
        json.dumps(
            {
                "timestamp": request_model.start_time.isoformat(),
                "service": request_model.service,
                "environment": request_model.environment,
                "level": "ERROR",
                "message": "Payment timeout",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "INVESTIGATOR_LOG_PATH",
        str(log_path),
    )

    def respond(request: httpx.Request) -> httpx.Response:
        if not actuator_available:
            raise httpx.ConnectError(
                "Unavailable",
                request=request,
            )

        if request.url.path.endswith("/info"):
            return httpx.Response(200, json={"app": APP_INFO})

        return httpx.Response(503, json={"status": "DOWN"})

    with httpx.Client(
        base_url=BASE_URL,
        transport=httpx.MockTransport(respond),
    ) as client:
        monkeypatch.setitem(
            app.dependency_overrides,
            get_metrics_collector,
            FakeMetricsCollector,
        )
        monkeypatch.setitem(
            app.dependency_overrides,
            get_actuator_collector,
            lambda: HttpActuatorCollector(client, target()),
        )

        with TestClient(app) as api:
            response = api.post(
                "/investigations",
                json=request_model.model_dump(mode="json"),
            )

    assert response.status_code == 200

    report = InvestigationReport.model_validate(response.json())

    assert report.analysis_status == "not_requested"

    expected = {EvidenceSource.LOG, EvidenceSource.METRIC}

    if actuator_available:
        expected.add(EvidenceSource.ACTUATOR)

    assert {item.source for item in report.evidence} == expected
    assert len(report.evidence) == (4 if actuator_available else 2)

    if not actuator_available:
        assert any("identity could not be verified" in issue for issue in report.missing_data)
