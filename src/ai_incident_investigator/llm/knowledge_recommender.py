import json
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter_ns
from typing import Annotated

from openai import APIError, OpenAI
from pydantic import AfterValidator, Field, ValidationError, create_model

from ai_incident_investigator.investigations.evidence_context import build_evidence_context
from ai_incident_investigator.investigations.reports import Identifier
from ai_incident_investigator.knowledge.recommendations import (
    InvestigationExport,
    KnowledgeCheck,
    KnowledgeRecommendations,
)
from ai_incident_investigator.knowledge.retrieval_context import ChunkId, KnowledgeContext
from ai_incident_investigator.llm.accounting import capture_usage
from ai_incident_investigator.llm.prompts import KNOWLEDGE_PROMPT
from ai_incident_investigator.usage.models import LLMUsage

PROMPT_SHA256 = sha256(KNOWLEDGE_PROMPT.encode("utf-8")).hexdigest()
MAX_INPUT_BYTES = 32_000


class RecommendationError(RuntimeError):
    """Knowledge recommendations could not be generated or validated."""

    def __init__(self, message: str, *, usage: LLMUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


@dataclass(frozen=True)
class RecommendationResult:
    recommendations: KnowledgeRecommendations
    usage: LLMUsage


def recommendation_schema(
    evidence_ids: Sequence[str], knowledge_ids: Sequence[str]
) -> type[KnowledgeRecommendations]:
    """Bind both citation namespaces in native JSON Schema and local validation."""
    evidence, knowledge = tuple(evidence_ids), tuple(knowledge_ids)
    known_evidence, known_knowledge = frozenset(evidence), frozenset(knowledge)
    if not knowledge or len(known_knowledge) != len(knowledge):
        raise ValueError("Knowledge IDs must be nonempty and unique")
    if len(known_evidence) != len(evidence) or known_evidence & known_knowledge:
        raise ValueError("Evidence IDs must be unique and disjoint from knowledge IDs")

    def validate_evidence(value: str) -> str:
        if value not in known_evidence:
            raise ValueError("Reference must identify supplied telemetry evidence")
        return value

    def validate_knowledge(value: str) -> str:
        if value not in known_knowledge:
            raise ValueError("Reference must identify a supplied knowledge chunk")
        return value

    BoundEvidenceId = Annotated[
        Identifier,
        Field(json_schema_extra={"enum": list(evidence)} if evidence else {}),
        AfterValidator(validate_evidence),
    ]
    BoundKnowledgeId = Annotated[
        ChunkId,
        Field(json_schema_extra={"enum": list(knowledge)}),
        AfterValidator(validate_knowledge),
    ]

    class BoundKnowledgeCheck(KnowledgeCheck):
        evidence_ids: tuple[BoundEvidenceId, ...] = Field(
            default=(), max_length=10 if evidence else 0
        )
        knowledge_ids: tuple[BoundKnowledgeId, ...] = Field(min_length=1, max_length=5)

    return create_model(
        "CitationBoundRecommendations",
        __base__=KnowledgeRecommendations,
        checks=(
            tuple[BoundKnowledgeCheck, ...],
            deepcopy(KnowledgeRecommendations.model_fields["checks"]),
        ),
    )


def build_input(investigation: InvestigationExport, context: KnowledgeContext) -> str:
    """Serialize original observations and reference data, excluding prior analysis."""
    request, report = investigation.request, investigation.report
    if context.service != request.service or context.environment != request.environment:
        raise RecommendationError("Knowledge context does not match the investigation scope")

    evidence_ids = {item.id for item in report.evidence}
    if evidence_ids & {hit.chunk.id for hit in context.chunks}:
        raise RecommendationError("Telemetry and knowledge IDs must be disjoint")

    payload = json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in report.evidence],
            "evidence_context": [
                item.model_dump(mode="json", exclude_none=True)
                for item in build_evidence_context(request, report.evidence)
            ],
            "missing_data": report.missing_data,
            "knowledge_context": context.model_dump(mode="json"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) + len(KNOWLEDGE_PROMPT.encode("utf-8")) > MAX_INPUT_BYTES:
        raise RecommendationError("Recommendation input exceeds the configured size limit")
    return payload


class OpenAIKnowledgeRecommender:
    def __init__(self, client: OpenAI, model: str) -> None:
        self.client = client.with_options(max_retries=0)
        self.model = model

    def recommend(
        self, investigation: InvestigationExport, context: KnowledgeContext
    ) -> RecommendationResult:
        if not context.chunks:
            raise RecommendationError("Recommendation generation requires knowledge context")

        payload = build_input(investigation, context)
        schema = recommendation_schema(
            [item.id for item in investigation.report.evidence],
            [hit.chunk.id for hit in context.chunks],
        )
        started_at = datetime.now(UTC)
        started = perf_counter_ns()
        body: object = None
        try:
            raw = self.client.responses.with_raw_response.parse(
                model=self.model,
                instructions=KNOWLEDGE_PROMPT,
                input=[{"role": "user", "content": payload}],
                text_format=schema,
                max_output_tokens=2000,
                store=False,
                service_tier="default",
            )
            body = raw.http_response.json()
            response = raw.parse()
        except (APIError, ValidationError, ValueError) as exc:
            usage = capture_usage(
                body,
                requested_model=self.model,
                started_at=started_at,
                duration_ms=(perf_counter_ns() - started) // 1_000_000,
            )
            raise RecommendationError(
                "Recommendation request failed or returned invalid data", usage=usage
            ) from exc

        usage = capture_usage(
            body,
            requested_model=self.model,
            started_at=started_at,
            duration_ms=(perf_counter_ns() - started) // 1_000_000,
        )
        if response.status != "completed" or response.output_parsed is None:
            raise RecommendationError("Model did not return completed recommendations", usage=usage)
        if any(
            part.type == "refusal"
            for item in response.output
            if item.type == "message"
            for part in item.content
        ):
            raise RecommendationError("Model refused the recommendations", usage=usage)

        return RecommendationResult(
            recommendations=KnowledgeRecommendations.model_validate(
                response.output_parsed.model_dump()
            ),
            usage=usage,
        )
