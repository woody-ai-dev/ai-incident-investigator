from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ai_incident_investigator.investigations.reports import (
    Identifier,
    InvestigationReport,
    ReportText,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.knowledge.embeddings import EmbeddingSpec
from ai_incident_investigator.knowledge.models import KnowledgeModel
from ai_incident_investigator.knowledge.retrieval_context import (
    ChunkId,
    ContextAssembly,
    NonNegativeInt,
)
from ai_incident_investigator.usage.models import LLMUsage

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class InvestigationExport(KnowledgeModel):
    schema_version: Literal[1]
    request: InvestigationRequest
    report: InvestigationReport

    @model_validator(mode="after")
    def validate_evidence_scope(self) -> Self:
        if any(item.service != self.request.service for item in self.report.evidence):
            raise ValueError("Export evidence must match the requested service")
        return self


class KnowledgeCheck(KnowledgeModel):
    action: ReportText
    reason: ReportText
    evidence_ids: tuple[Identifier, ...] = Field(default=(), max_length=10)
    knowledge_ids: tuple[ChunkId, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_unique_references(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Check evidence IDs must be unique")
        if len(self.knowledge_ids) != len(set(self.knowledge_ids)):
            raise ValueError("Check knowledge IDs must be unique")
        return self


class KnowledgeRecommendations(KnowledgeModel):
    checks: tuple[KnowledgeCheck, ...] = Field(max_length=5)
    limitations: tuple[ReportText, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def validate_abstention(self) -> Self:
        if not self.checks and not self.limitations:
            raise ValueError("An empty recommendation set requires an explanation")
        return self


class RecommendationArtifact(KnowledgeModel):
    schema_version: Literal[1] = 1
    status: Literal["completed", "skipped", "failed"]
    input_sha256: Sha256
    query: str = Field(min_length=1, max_length=4000)
    investigation: InvestigationExport
    mode: Literal["approved", "preview"]
    collection: str | None
    embedding: EmbeddingSpec
    embedding_total_tokens: NonNegativeInt | None
    model: str = Field(min_length=1, max_length=200)
    prompt_sha256: Sha256
    assembly: ContextAssembly | None
    recommendations: KnowledgeRecommendations | None
    generation_usage: LLMUsage | None
    issue: ReportText | None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        evidence_ids = {item.id for item in self.investigation.report.evidence}
        knowledge_ids: set[str] = set()
        if self.assembly is not None:
            context = self.assembly.context
            request = self.investigation.request
            if context.service != request.service or context.environment != request.environment:
                raise ValueError("Recommendation context must match the investigation scope")
            if context.mode != self.mode:
                raise ValueError("Recommendation context mode must match the artifact")
            knowledge_ids = {hit.chunk.id for hit in context.chunks}

        if evidence_ids & knowledge_ids:
            raise ValueError("Evidence and knowledge IDs must be disjoint")

        if self.status == "completed":
            if not knowledge_ids or self.recommendations is None or self.generation_usage is None:
                raise ValueError("Completed recommendations require context, output and usage")
            if self.issue is not None:
                raise ValueError("Completed recommendations cannot contain a failure issue")
            for check in self.recommendations.checks:
                if not set(check.evidence_ids) <= evidence_ids:
                    raise ValueError("Recommendation references unknown evidence")
                if not set(check.knowledge_ids) <= knowledge_ids:
                    raise ValueError("Recommendation references unknown knowledge")
        else:
            if self.recommendations is not None or self.issue is None:
                raise ValueError("Skipped or failed recommendations require an issue and no output")
            if self.status == "skipped" and (
                self.assembly is None or knowledge_ids or self.generation_usage is not None
            ):
                raise ValueError("Skipped recommendations require an empty context and no usage")
        return self
