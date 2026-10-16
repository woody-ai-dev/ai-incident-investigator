import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import httpx2 as httpx
import pytest
from openai import OpenAI
from pydantic import ValidationError

from ai_incident_investigator.investigations.analysis import Analysis, AnalysisError
from ai_incident_investigator.investigations.reports import (
    Evidence,
    EvidenceSource,
    Finding,
    Hypothesis,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.llm.openai_client import OpenAIAnalyzer
from ai_incident_investigator.llm.response_schema import analysis_schema


@pytest.fixture
def analysis_payload() -> dict[str, Any]:
    return {
        "summary": "A payment timeout was recorded; its cause is unconfirmed.",
        "findings": [{"statement": "A timeout was logged.", "evidence_ids": ["log-1"]}],
        "hypotheses": [
            {
                "statement": "The payment dependency may be slow.",
                "supporting_evidence_ids": ["log-1"],
                "contradicting_evidence_ids": ["metric-1"],
            }
        ],
        "recommended_checks": [
            {"action": "Inspect payment traces.", "reason": "The cause is unconfirmed."}
        ],
    }


def assert_reference_enums(schema: dict[str, Any], expected: list[str]) -> None:
    definitions = schema["$defs"]
    finding_schema = definitions["BoundFinding"]["properties"]["evidence_ids"]
    hypothesis_schema = definitions["BoundHypothesis"]["properties"]

    for field in (
        finding_schema,
        hypothesis_schema["supporting_evidence_ids"],
        hypothesis_schema["contradicting_evidence_ids"],
    ):
        assert field["items"]["type"] == "string"
        assert field["items"]["enum"] == expected
        assert field["items"]["minLength"] == 1
        assert field["items"]["maxLength"] == 100


def test_bound_schema_preserves_valid_analysis(
    analysis_payload: dict[str, Any],
) -> None:
    schema = analysis_schema(["log-1", "metric-1"])
    result = schema.model_validate(analysis_payload)

    assert isinstance(result, Analysis)
    assert result.model_dump() == Analysis.model_validate(analysis_payload).model_dump()
    assert_reference_enums(schema.model_json_schema(), ["log-1", "metric-1"])


@pytest.mark.parametrize(
    ("collection", "field"),
    [
        ("findings", "evidence_ids"),
        ("hypotheses", "supporting_evidence_ids"),
        ("hypotheses", "contradicting_evidence_ids"),
    ],
)
def test_unknown_references_are_rejected_locally(
    analysis_payload: dict[str, Any], collection: str, field: str
) -> None:
    analysis_payload[collection][0][field] = ["_missing_"]

    with pytest.raises(ValidationError, match="Reference must identify evidence"):
        analysis_schema(["log-1", "metric-1"]).model_validate(analysis_payload)


def test_schemas_are_independent_and_do_not_mutate_base_models(
    analysis_payload: dict[str, Any],
) -> None:
    base_schemas = [model.model_json_schema() for model in (Analysis, Finding, Hypothesis)]
    first = analysis_schema(["log-1", "metric-1"])
    second = analysis_schema(["other-1"])

    assert_reference_enums(first.model_json_schema(), ["log-1", "metric-1"])
    assert_reference_enums(second.model_json_schema(), ["other-1"])
    first.model_validate(analysis_payload)

    with pytest.raises(ValidationError, match="Reference must identify evidence"):
        second.model_validate(analysis_payload)

    assert base_schemas == [model.model_json_schema() for model in (Analysis, Finding, Hypothesis)]
    unrestricted = deepcopy(analysis_payload)
    unrestricted["findings"][0]["evidence_ids"] = ["unbound-id"]
    Analysis.model_validate(unrestricted)


@pytest.mark.parametrize("evidence_ids", [[], ["log-1", "log-1"]])
def test_invalid_evidence_sets_are_rejected(evidence_ids: list[str]) -> None:
    with pytest.raises(ValueError):
        analysis_schema(evidence_ids)


@pytest.mark.parametrize(
    ("collection", "count"),
    [
        ("findings", 11),
        ("hypotheses", 6),
        ("recommended_checks", 0),
        ("recommended_checks", 11),
    ],
)
def test_analysis_collection_bounds_are_preserved(
    analysis_payload: dict[str, Any], collection: str, count: int
) -> None:
    analysis_payload[collection] = analysis_payload[collection] * count

    with pytest.raises(ValidationError):
        analysis_schema(["log-1", "metric-1"]).model_validate(analysis_payload)


@pytest.mark.parametrize(
    ("collection", "field"),
    [("findings", "evidence_ids"), ("hypotheses", "supporting_evidence_ids")],
)
def test_required_reference_lists_remain_nonempty(
    analysis_payload: dict[str, Any], collection: str, field: str
) -> None:
    analysis_payload[collection][0][field] = []

    with pytest.raises(ValidationError):
        analysis_schema(["log-1", "metric-1"]).model_validate(analysis_payload)


def test_optional_contradicting_references_keep_their_default(
    analysis_payload: dict[str, Any],
) -> None:
    del analysis_payload["hypotheses"][0]["contradicting_evidence_ids"]

    result = analysis_schema(["log-1", "metric-1"]).model_validate(analysis_payload)

    assert result.hypotheses[0].contradicting_evidence_ids == []


@pytest.mark.parametrize("invalid_reference", [False, True])
def test_adapter_sends_native_enums_and_returns_base_analysis(
    analysis_payload: dict[str, Any], invalid_reference: bool
) -> None:
    request_model = InvestigationRequest(
        service="order-service",
        environment="local",
        start_time=datetime(2026, 10, 2, 19, 0, tzinfo=UTC),
        end_time=datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
    )
    evidence = [
        Evidence(
            id=identifier,
            source=EvidenceSource.LOG if identifier == "log-1" else EvidenceSource.METRIC,
            service="order-service",
            summary="A recorded observation.",
            reference="local-jsonl:line:1" if identifier == "log-1" else "prometheus:query:1",
            start_time=request_model.start_time,
        )
        for identifier in ("log-1", "metric-1")
    ]
    calls = 0
    if invalid_reference:
        analysis_payload["findings"][0]["evidence_ids"] = ["_missing_"]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        assert body["text"]["format"]["strict"] is True
        assert_reference_enums(body["text"]["format"]["schema"], ["log-1", "metric-1"])
        return httpx.Response(
            200,
            json={
                "id": "resp_bound_test",
                "object": "response",
                "created_at": 1,
                "model": "test-model",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_bound_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(analysis_payload),
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
        )

    with OpenAI(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        analyzer = OpenAIAnalyzer(client, "test-model")

        if invalid_reference:
            with pytest.raises(AnalysisError):
                analyzer.analyze(request_model, evidence, [])
        else:
            result = analyzer.analyze(request_model, evidence, [])
            assert type(result) is Analysis
            assert result == Analysis.model_validate(analysis_payload)

    assert calls == 1
