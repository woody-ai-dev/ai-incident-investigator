import json
import re
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter_ns
from typing import Annotated, Self

from openai import APIError, OpenAI
from pydantic import AfterValidator, Field, ValidationError, create_model, model_validator

from ai_incident_investigator.investigations.evidence_context import build_evidence_context
from ai_incident_investigator.investigations.reports import Identifier, ReportText, SourceCollection
from ai_incident_investigator.knowledge.models import KnowledgeModel
from ai_incident_investigator.knowledge.recommendations import (
    InvestigationExport,
    KnowledgeCheck,
    KnowledgeRecommendations,
)
from ai_incident_investigator.knowledge.retrieval_context import KnowledgeContext
from ai_incident_investigator.llm.accounting import capture_usage
from ai_incident_investigator.llm.prompts import KNOWLEDGE_PROMPT
from ai_incident_investigator.usage.models import LLMUsage

PROMPT_SHA256 = sha256(KNOWLEDGE_PROMPT.encode("utf-8")).hexdigest()
MAX_INPUT_BYTES = 32_000
HISTORICAL_CHECK_CONDITION = (
    "For historical verification, use supplied incident data or, if available, "
    "retained records or configuration covering the requested incident window. "
)


class RecommendationError(RuntimeError):
    """Knowledge recommendations could not be generated or validated."""

    def __init__(self, message: str, *, usage: LLMUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


@dataclass(frozen=True)
class RecommendationResult:
    recommendations: KnowledgeRecommendations
    usage: LLMUsage


@dataclass(frozen=True)
class KnowledgeInstruction:
    knowledge_id: str
    text: str


class RecommendationChoice(KnowledgeModel):
    instruction_index: int = Field(strict=True, ge=0)
    reason: ReportText
    evidence_ids: tuple[Identifier, ...] = Field(default=(), max_length=10)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Check evidence IDs must be unique")
        return self


class RecommendationPlan(KnowledgeModel):
    checks: tuple[RecommendationChoice, ...] = Field(max_length=5)
    limitations: tuple[ReportText, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def validate_abstention(self) -> Self:
        if not self.checks and not self.limitations:
            raise ValueError("An empty recommendation set requires an explanation")
        return self


def instruction_choices(
    context: KnowledgeContext, source_collections: Sequence[SourceCollection] | None = None
) -> tuple[KnowledgeInstruction, ...]:
    choices = []
    statuses = {item.status for item in source_collections or ()}
    for hit in context.chunks:
        normalized = hit.chunk.content.replace("\r\n", "\n").replace("\r", "\n")
        for paragraph in re.split(r"\n\s*\n", normalized):
            paragraph = paragraph.strip()
            conditions = [
                condition
                for condition in hit.chunk.document.instruction_conditions or ()
                if paragraph.startswith(condition.prefix)
            ]
            if conditions and not any(
                statuses.intersection(condition.statuses) for condition in conditions
            ):
                continue
            # Keep complete conditions and negations, reserving room for the condition.
            if paragraph and not paragraph.startswith("#") and len(paragraph) <= 3800:
                choices.append(KnowledgeInstruction(hit.chunk.id, paragraph))
    return tuple(choices)


def render_recommendations(
    plan: RecommendationPlan, instructions: Sequence[KnowledgeInstruction]
) -> KnowledgeRecommendations:
    return KnowledgeRecommendations(
        checks=tuple(
            KnowledgeCheck(
                action=HISTORICAL_CHECK_CONDITION + instructions[check.instruction_index].text,
                reason=check.reason,
                evidence_ids=check.evidence_ids,
                knowledge_ids=(instructions[check.instruction_index].knowledge_id,),
            )
            for check in plan.checks
        ),
        limitations=plan.limitations,
    )


def recommendation_schema(
    evidence_ids: Sequence[str], instructions: Sequence[KnowledgeInstruction]
) -> type[RecommendationPlan]:
    """Bind instruction choices and telemetry references before requesting a plan."""
    evidence = tuple(evidence_ids)
    known_evidence = frozenset(evidence)
    known_knowledge = {item.knowledge_id for item in instructions}
    if not instructions:
        raise ValueError("Knowledge instructions must be nonempty")
    if len(known_evidence) != len(evidence) or known_evidence & known_knowledge:
        raise ValueError("Evidence IDs must be unique and disjoint from knowledge IDs")

    def validate_evidence(value: str) -> str:
        if value not in known_evidence:
            raise ValueError("Reference must identify supplied telemetry evidence")
        return value

    BoundEvidenceId = Annotated[
        Identifier,
        Field(json_schema_extra={"enum": list(evidence)} if evidence else {}),
        AfterValidator(validate_evidence),
    ]

    class BoundRecommendationChoice(RecommendationChoice):
        instruction_index: int = Field(strict=True, ge=0, le=len(instructions) - 1)
        evidence_ids: tuple[BoundEvidenceId, ...] = Field(
            default=(), max_length=10 if evidence else 0
        )

    return create_model(
        "InstructionBoundRecommendations",
        __base__=RecommendationPlan,
        checks=(
            tuple[BoundRecommendationChoice, ...],
            deepcopy(RecommendationPlan.model_fields["checks"]),
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

    instructions = instruction_choices(context, report.source_collections)
    if context.chunks and not instructions:
        raise RecommendationError("No complete instruction fits the action budget")

    payload = json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in report.evidence],
            "evidence_context": [
                item.model_dump(mode="json", exclude_none=True)
                for item in build_evidence_context(request, report.evidence)
            ],
            "source_collections": (
                [item.model_dump(mode="json") for item in report.source_collections]
                if report.source_collections is not None
                else None
            ),
            "missing_data": report.missing_data,
            "knowledge_context": {
                "mode": context.mode,
                "service": context.service,
                "environment": context.environment,
                "chunks": [
                    {
                        "knowledge_id": hit.chunk.id,
                        "document_id": hit.chunk.document.id,
                        "section": hit.chunk.section,
                        "instructions": {
                            str(index): instruction.text
                            for index, instruction in enumerate(instructions)
                            if instruction.knowledge_id == hit.chunk.id
                        },
                    }
                    for hit in context.chunks
                ],
            },
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
        instructions = instruction_choices(context, investigation.report.source_collections)
        schema = recommendation_schema(
            [item.id for item in investigation.report.evidence], instructions
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
                temperature=0,
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
            recommendations=render_recommendations(
                RecommendationPlan.model_validate(response.output_parsed.model_dump()), instructions
            ),
            usage=usage,
        )
