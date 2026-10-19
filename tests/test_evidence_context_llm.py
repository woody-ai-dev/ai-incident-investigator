import json
from datetime import UTC, datetime

import httpx2 as httpx
import pytest
from openai import OpenAI

from ai_incident_investigator.investigations.analysis import AnalysisError
from ai_incident_investigator.investigations.reports import Evidence, EvidenceSource
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.llm import openai_client
from ai_incident_investigator.llm.openai_client import OpenAIAnalyzer


@pytest.fixture
def incident() -> InvestigationRequest:
    return InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2026, 10, 17, 19, 0, tzinfo=UTC),
        end_time=datetime(2026, 10, 17, 19, 5, tzinfo=UTC),
    )


@pytest.fixture
def snapshot() -> Evidence:
    return Evidence(
        id="actuator-health",
        source=EvidenceSource.ACTUATOR,
        service="order-service",
        summary="The health endpoint reported UP at the snapshot time.",
        reference="test:health",
        start_time=datetime(2026, 10, 17, 20, 0, tzinfo=UTC),
    )


@pytest.mark.parametrize("include_metric", [False, True])
def test_adapter_sends_context_as_input_data(
    incident: InvestigationRequest,
    snapshot: Evidence,
    include_metric: bool,
) -> None:
    calls = 0
    evidence = [snapshot]
    if include_metric:
        evidence.append(
            Evidence(
                id="metric-up",
                source=EvidenceSource.METRIC,
                service=incident.service,
                summary="Returned scrape evaluations: min=1, max=1, last=1.",
                reference="test:metric-up",
                start_time=incident.start_time,
                end_time=incident.end_time,
            )
        )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        payload = json.loads(body["input"][0]["content"])

        assert payload["request"] == incident.model_dump(mode="json")
        assert payload["evidence"] == [item.model_dump(mode="json") for item in evidence]
        assert payload["missing_data"] == ["No historical health snapshots."]
        assert payload["evidence_context"][0] == {
            "evidence_id": "actuator-health",
            "observation_kind": "point_observation",
            "time_scope": "after_window",
        }
        assert len(payload["evidence_context"]) == len(evidence)
        if include_metric:
            metric_context = payload["evidence_context"][1]
            assert metric_context["evidence_id"] == "metric-up"
            assert metric_context["metric_interpretation"]["kind"] == "scrape_success"
            assert metric_context["metric_interpretation"]["limitations"]
        assert "evidence_context" not in body["text"]["format"]["schema"]["properties"]
        assert body["store"] is False

        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "model": "test-model",
                "status": "incomplete",
                "output": [],
            },
        )

    with OpenAI(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(AnalysisError, match="completed analysis"):
            OpenAIAnalyzer(client, "test-model").analyze(
                incident, evidence, ["No historical health snapshots."]
            )

    assert calls == 1


def test_input_budget_includes_context(
    incident: InvestigationRequest,
    snapshot: Evidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    without_context = json.dumps(
        {
            "request": incident.model_dump(mode="json"),
            "evidence": [snapshot.model_dump(mode="json")],
            "missing_data": [],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(openai_client, "MAX_INPUT_BYTES", len(without_context.encode("utf-8")) + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Input must be rejected before any provider request")

    with OpenAI(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(AnalysisError, match="size limit"):
            OpenAIAnalyzer(client, "test-model").analyze(incident, [snapshot], [])
