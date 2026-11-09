from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from ai_incident_investigator.investigations.reports import ReportText
from ai_incident_investigator.knowledge.models import Identifier, KnowledgeModel
from ai_incident_investigator.knowledge.retrieval_chunks import RetrievalChunk

Section = Annotated[str, Field(min_length=1, max_length=1000)]


class PassageLabel(KnowledgeModel):
    document_id: Identifier
    section: Section
    text_contains: ReportText | None = None


class ContextCase(KnowledgeModel):
    id: Identifier
    query: ReportText
    expected_status: Literal["completed", "skipped"]
    expected_issue: ReportText | None = None
    expected_context: tuple[PassageLabel, ...]
    review_questions: tuple[ReportText, ...]

    @field_validator("expected_context")
    @classmethod
    def validate_labels(cls, labels: tuple[PassageLabel, ...]) -> tuple[PassageLabel, ...]:
        keys = {
            (label.document_id, label.section, " ".join((label.text_contains or "").split()))
            for label in labels
        }
        if len(keys) != len(labels):
            raise ValueError("Expected passages must be unique")
        return labels


class ContextDataset(KnowledgeModel):
    schema_version: Literal[1]
    cases: tuple[ContextCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_ids(self) -> Self:
        case_ids = {case.id for case in self.cases}
        if len(case_ids) != len(self.cases):
            raise ValueError("Context case IDs must be unique")
        return self


def case_export_path(dataset: Path, case: ContextCase) -> Path:
    return dataset.parent / "fixtures" / "knowledge-recommendations" / f"{case.id}.json"


def matching_chunk_ids(label: PassageLabel, chunks: tuple[RetrievalChunk, ...]) -> list[str]:
    phrase = " ".join((label.text_contains or "").split())
    return [
        chunk.id
        for chunk in chunks
        if chunk.document.id == label.document_id
        and chunk.section == label.section
        and phrase in " ".join(chunk.content.split())
    ]
