import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate
from ai_incident_investigator.llm.accounting import capture_usage
from ai_incident_investigator.llm.openai_client import OpenAIAnalyzer
from ai_incident_investigator.main import create_app
from ai_incident_investigator.usage.models import LLMUsage

MODEL = "gpt-4.1-mini-2025-04-14"
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def response_body(mode: str = "success") -> dict[str, object]:
    analysis = {
        "summary": "A timeout was logged.",
        "findings": [{"statement": "Timeout recorded.", "evidence_ids": ["log-1"]}],
        "hypotheses": [],
        "recommended_checks": [
            {"action": "Inspect payment latency.", "reason": "Cause is unknown."}
        ],
    }
    if mode == "bad_reference":
        analysis["findings"] = [{"statement": "Timeout recorded.", "evidence_ids": ["invented"]}]
    content = [{"type": "output_text", "text": json.dumps(analysis), "annotations": []}]
    if mode == "invalid":
        content = [{"type": "output_text", "text": "{}", "annotations": []}]
    if mode == "refusal":
        content = [{"type": "refusal", "refusal": "Cannot analyze."}]
    return {
        "id": "resp_usage_test",
        "object": "response",
        "created_at": 1,
        "model": MODEL,
        "service_tier": "default",
        "status": "incomplete" if mode == "incomplete" else "completed",
        "usage": {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 400},
            "output_tokens": 100,
            "total_tokens": 1100,
        },
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": content,
            }
        ],
    }


def test_cached_tokens_are_not_counted_twice() -> None:
    usage = capture_usage(response_body(), requested_model=MODEL, started_at=NOW, duration_ms=100)
    assert usage.tokens is not None and usage.tokens.total_tokens == 1100
    assert usage.estimated_cost_usd == Decimal("0.00044")
    assert LLMUsage.model_validate_json(usage.model_dump_json()) == usage
    assert usage.model_dump(mode="json")["estimated_cost_usd"] == "0.00044"


@pytest.mark.parametrize(
    "change", [{"model": "unknown"}, {"service_tier": "flex"}, {"usage": None}]
)
def test_unknown_data_is_unpriced(change: dict[str, object]) -> None:
    usage = capture_usage(
        response_body() | change, requested_model=MODEL, started_at=NOW, duration_ms=1
    )
    assert usage.estimated_cost_usd is None


@pytest.mark.parametrize(
    "mode", ["success", "invalid", "refusal", "incomplete", "bad_reference", "http", "timeout"]
)
def test_usage_survives_rejected_or_failed_analysis(tmp_path: Path, mode: str) -> None:
    request = InvestigationRequest(
        service="order-service", environment="local", start_time=NOW, end_time=NOW.replace(minute=5)
    )
    path = tmp_path / "logs.jsonl"
    path.write_text(
        json.dumps(
            {
                "timestamp": NOW.isoformat(),
                "service": "order-service",
                "environment": "local",
                "level": "ERROR",
                "message": "Payment timeout",
            }
        )
        + "\n"
    )
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        if mode == "http":
            return httpx2.Response(500, json={"error": {"message": "Unavailable"}})
        if mode == "timeout":
            raise httpx2.ReadTimeout("Test timeout", request=request)
        return httpx2.Response(200, json=response_body(mode))

    with OpenAI(
        api_key="test-key",
        max_retries=2,
        base_url="https://example.invalid/v1",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    ) as client:
        report = investigate(request, log_path=path, analyzer=OpenAIAnalyzer(client, MODEL))
    assert calls == 1
    assert report.analysis_status == ("completed" if mode == "success" else "failed")
    assert report.llm_usage is not None
    assert report.llm_usage.estimated_cost_usd == (
        None if mode in {"http", "timeout"} else Decimal("0.00044")
    )
    assert report.evidence


def test_billing_metadata_is_not_in_the_generated_schema() -> None:
    from ai_incident_investigator.llm.response_schema import analysis_schema

    assert "llm_usage" not in analysis_schema(["log-1"]).model_json_schema()["properties"]


def test_usage_requires_storage() -> None:
    with TestClient(create_app()) as client:
        assert client.get("/usage").status_code == 503
        assert client.get("/usage?days=31").status_code == 422
        assert client.get("/usage?sort=invalid").status_code == 422
