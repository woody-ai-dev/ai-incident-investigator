from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=100)]
ReportText = Annotated[str, Field(min_length=1, max_length=4000)]


class EvidenceSource(StrEnum):
    LOG = "log"
    METRIC = "metric"
    TRACE = "trace"
    ACTUATOR = "actuator"


class ReportModel(BaseModel):
    """Shared validation rules for report models."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(ReportModel):
    """An observation with a reference to its source data."""

    id: Identifier
    source: EvidenceSource
    service: Identifier
    summary: ReportText
    reference: ReportText
    start_time: AwareDatetime
    end_time: AwareDatetime | None = None

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def parse_timestamp(cls, value: object) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value

        if isinstance(value, str):
            return datetime.fromisoformat(value)

        raise ValueError("timestamp must be an ISO 8601 string or a datetime object")

    @field_validator("start_time", "end_time")
    @classmethod
    def normilixe_timestamp(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")

        return self


class Finding(ReportModel):
    statement: ReportText
    evidence_ids: list[Identifier] = Field(min_length=1)


class Hypothesis(ReportModel):
    statement: ReportText
    supporting_evidence_ids: list[Identifier] = Field(min_length=1)
    contradicting_evidence_ids: list[Identifier] = Field(default_factory=list)


class RecommendedCheck(ReportModel):
    action: ReportText
    reason: ReportText


class CollectionStatus(StrEnum):
    COLLECTED = "collected"
    PARTIAL = "partial"
    EMPTY = "empty"
    DISABLED = "disabled"
    SKIPPED = "skipped"
    ERROR = "error"
    NOT_RECORDED = "not_recorded"


class SourceCollection(ReportModel):
    source: EvidenceSource
    status: CollectionStatus
    evidence_count: int = Field(ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    issues: list[ReportText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        no_evidence = {
            CollectionStatus.EMPTY,
            CollectionStatus.DISABLED,
            CollectionStatus.SKIPPED,
            CollectionStatus.ERROR,
        }

        if self.status in no_evidence and self.evidence_count != 0:
            raise ValueError("This collection status cannot contain evidence")

        if self.status == CollectionStatus.COLLECTED and self.evidence_count == 0:
            raise ValueError("Collected status requires evidence")

        if self.status == CollectionStatus.DISABLED and self.duration_ms is not None:
            raise ValueError("Disabled collection must not have a measured duration")

        if self.status not in {CollectionStatus.DISABLED, CollectionStatus.NOT_RECORDED}:
            if self.duration_ms is None:
                raise ValueError("Executed collection requires duration_ms")

        if (
            self.status
            in {
                CollectionStatus.PARTIAL,
                CollectionStatus.DISABLED,
                CollectionStatus.SKIPPED,
                CollectionStatus.ERROR,
            }
            and not self.issues
        ):
            raise ValueError("Incomplete or unavailable collection requires an explanation")

        return self


class InvestigationReport(ReportModel):
    analysis_status: Literal["not_requested", "skipped", "completed", "failed"] = "not_requested"
    source_collections: list[SourceCollection] | None = Field(
        default=None,
        min_length=1,
        max_length=4,
        exclude_if=lambda value: value is None,
    )

    summary: ReportText
    evidence: list[Evidence]
    findings: list[Finding]
    hypotheses: list[Hypothesis]
    recommended_checks: list[RecommendedCheck]
    missing_data: list[ReportText]

    @model_validator(mode="after")
    def validate_evidence_references(self) -> Self:
        evidence_ids = [item.id for item in self.evidence]
        known_ids = set(evidence_ids)

        if len(evidence_ids) != len(known_ids):
            raise ValueError("evidence IDs must be unique")

        referenced_ids: set[str] = set()

        for finding in self.findings:
            referenced_ids.update(finding.evidence_ids)

        for hypothesis in self.hypotheses:
            referenced_ids.update(hypothesis.supporting_evidence_ids)
            referenced_ids.update(hypothesis.contradicting_evidence_ids)

        unknown_ids = referenced_ids - known_ids

        if unknown_ids:
            raise ValueError(f"unknown evidence IDs: {', '.join(sorted(unknown_ids))}")

        if self.source_collections is not None:
            sources = [item.source for item in self.source_collections]

            if len(sources) != len(set(sources)):
                raise ValueError("Collection sources must be unique")

            for collection in self.source_collections:
                actual_count = sum(item.source == collection.source for item in self.evidence)

                if collection.evidence_count != actual_count:
                    raise ValueError("Collection evidence_count must match report evidence")

        if not self.evidence and not self.missing_data:
            raise ValueError("missing_data must explain why no evidence is available")

        return self
