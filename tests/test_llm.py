import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI
from pydantic import ValidationError

from ai_incident_investigator.investigations.analysis import Analysis, AnalysisError
from ai_incident_investigator.investigations.reports import Evidence, InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate
from ai_incident_investigator.llm.dependencies import get_analyzer
from ai_incident_investigator.llm.openai_client import OpenAIAnalyzer
from ai_incident_investigator.main import app
from ai_incident_investigator.settings import get_settings


@pytest.fixture
def request_model() -> InvestigationRequest:
    return InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2026, 10, 2, 19, 0, tzinfo=UTC),
        end_time=datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
    )


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    path = tmp_path / "logs.jsonl"

    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-10-02T19:40:00Z",
                "service": "order-service",
                "environment": "local",
                "level": "ERROR",
                "message": "Payment request timed out (simulated).",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    return path


@pytest.fixture
def analysis() -> Analysis:
    return Analysis.model_validate(
        {
            "summary": "A simulated payment timeout was recorded.",
            "findings": [
                {
                    "statement": "A timeout was logged.",
                    "evidence_ids": ["log-1"],
                }
            ],
            "hypotheses": [],
            "recommended_checks": [
                {
                    "action": "Inspect the payment trace.",
                    "reason": "The cause is unknown.",
                }
            ],
        }
    )


class StubAnalyzer:
    def __init__(self, result: Analysis | None) -> None:
        self.result = result
        self.calls = 0

    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis:
        self.calls += 1

        if self.result is None:
            raise AnalysisError("Test failure")

        return self.result


@pytest.mark.parametrize("mode", ["success", "error", "unknown_reference"])
def test_analysis_integration(
    request_model: InvestigationRequest,
    log_path: Path,
    analysis: Analysis,
    mode: str,
) -> None:
    if mode == "unknown_reference":
        analysis.findings[0].evidence_ids = ["invented-id"]

    analyzer = StubAnalyzer(None if mode == "error" else analysis)

    report = investigate(request_model, log_path=log_path, analyzer=analyzer)

    assert analyzer.calls == 1
    assert len(report.evidence) == 1
    assert report.analysis_status == ("completed" if mode == "success" else "failed")
    assert any("Prometheus" in item for item in report.missing_data)

    if mode == "success":
        assert report.findings[0].evidence_ids == ["log-1"]
    else:
        assert report.findings == []
        assert any("LLM analysis failed" in item for item in report.missing_data)


def test_no_evidence_skips_llm(
    request_model: InvestigationRequest,
    tmp_path: Path,
) -> None:
    analyzer = StubAnalyzer(None)

    report = investigate(
        request_model,
        log_path=tmp_path / "missing.jsonl",
        analyzer=analyzer,
    )

    assert analyzer.calls == 0
    assert report.analysis_status == "skipped"


def test_disabled_analysis(
    request_model: InvestigationRequest,
    log_path: Path,
) -> None:
    report = investigate(request_model, log_path=log_path)

    assert report.analysis_status == "not_requested"
    assert len(report.evidence) == 1


def response_body(analysis: Analysis, mode: str) -> dict[str, object]:
    content: list[dict[str, object]] = [
        {
            "type": "output_text",
            "text": analysis.model_dump_json(),
            "annotations": [],
        }
    ]

    if mode == "refusal":
        content = [{"type": "refusal", "refusal": "Cannot analyze."}]

    if mode == "invalid":
        content = [{"type": "output_text", "text": "{}", "annotations": []}]

    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "test-model",
        "status": "incomplete" if mode == "incomplete" else "completed",
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


@pytest.mark.parametrize(
    "mode",
    ["success", "refusal", "invalid", "incomplete", "http", "timeout"],
)
def test_openai_adapter(
    request_model: InvestigationRequest,
    log_path: Path,
    analysis: Analysis,
    mode: str,
) -> None:
    evidence = investigate(request_model, log_path=log_path).evidence

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)

        assert body["store"] is False
        assert body["text"]["format"]["strict"] is True
        assert body["max_output_tokens"] == 2500

        payload = json.loads(body["input"][0]["content"])

        assert payload["evidence"][0]["id"] == "log-1"
        assert payload["missing_data"] == ["Traces unavailable."]

        if mode == "timeout":
            raise httpx.ReadTimeout("Test timeout", request=request)

        if mode == "http":
            return httpx.Response(
                500,
                json={"error": {"message": "Unavailable"}},
            )

        return httpx.Response(200, json=response_body(analysis, mode))

    with OpenAI(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        analyzer = OpenAIAnalyzer(client, "test-model")

        if mode == "success":
            result = analyzer.analyze(
                request_model,
                evidence,
                ["Traces unavailable."],
            )

            assert result == analysis
        else:
            with pytest.raises(AnalysisError):
                analyzer.analyze(
                    request_model,
                    evidence,
                    ["Traces unavailable."],
                )


def test_oversized_input_does_not_call_provider(
    request_model: InvestigationRequest,
    log_path: Path,
) -> None:
    evidence = investigate(request_model, log_path=log_path).evidence

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Provider must not be called")

    with OpenAI(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(AnalysisError, match="size limit"):
            OpenAIAnalyzer(client, "test-model").analyze(
                request_model,
                evidence,
                ["x" * 32_000],
            )


def test_enabled_llm_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_ENABLED", "true")

    with pytest.raises(ValidationError, match="OPENAI_API_KEY is required"):
        get_settings()


def test_api_uses_injected_analyzer(
    request_model: InvestigationRequest,
    log_path: Path,
    analysis: Analysis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVESTIGATOR_LOG_PATH", str(log_path))
    analyzer = StubAnalyzer(analysis)

    app.dependency_overrides[get_analyzer] = lambda: analyzer

    try:
        with TestClient(app) as client:
            response = client.post(
                "/investigations",
                json=request_model.model_dump(mode="json"),
            )

        assert response.status_code == 200

        report = InvestigationReport.model_validate(response.json())

        assert report.analysis_status == "completed"
        assert report.findings[0].evidence_ids == ["log-1"]
    finally:
        app.dependency_overrides.pop(get_analyzer, None)


def test_provider_retries_are_bounded(
    request_model: InvestigationRequest,
    log_path: Path,
) -> None:
    evidence = investigate(request_model, log_path=log_path).evidence
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1

        return httpx.Response(
            429,
            headers={"retry-after-ms": "1"},
            json={"error": {"message": "Rate limited"}},
        )

    with OpenAI(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        max_retries=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(AnalysisError):
            OpenAIAnalyzer(client, "test-model").analyze(
                request_model,
                evidence,
                [],
            )

    assert calls == 2


def test_settings_do_not_display_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-value")

    settings = get_settings()

    assert "test-secret-value" not in repr(settings)
    assert "test-secret-value" not in settings.model_dump_json()
