from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ai_incident_investigator.evaluation.review import ReviewModel, ReviewStatus, Verdict
from ai_incident_investigator.knowledge.recommendations import (
    KnowledgeRecommendations,
    RecommendationArtifact,
    Sha256,
)


class KnowledgeCheckReview(ReviewModel):
    check_index: Annotated[int, Field(strict=True, ge=0)]
    knowledge_support: Verdict
    evidence_relevance: Verdict
    temporal_correctness: Verdict
    actionability: Verdict
    notes: str = Field(max_length=4000)

    @property
    def verdicts(self) -> tuple[Verdict, ...]:
        return (
            self.knowledge_support,
            self.evidence_relevance,
            self.temporal_correctness,
            self.actionability,
        )

    @model_validator(mode="after")
    def require_review_notes(self) -> Self:
        if any(verdict != Verdict.NOT_REVIEWED for verdict in self.verdicts) and not self.notes:
            raise ValueError("Reviewed check criteria require explanatory notes")
        return self


class KnowledgeReview(ReviewModel):
    schema_version: Literal[1]
    source_sha256: Sha256
    reviewer: str = Field(max_length=100)
    response_appropriateness: Verdict
    limitations: Verdict
    notes: str = Field(max_length=4000)
    checks: list[KnowledgeCheckReview]

    @property
    def verdicts(self) -> tuple[Verdict, ...]:
        return (
            self.response_appropriateness,
            self.limitations,
            *(verdict for check in self.checks for verdict in check.verdicts),
        )

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        global_decisions = (self.response_appropriateness, self.limitations)
        if any(verdict != Verdict.NOT_REVIEWED for verdict in global_decisions) and not self.notes:
            raise ValueError("Reviewed response criteria require explanatory notes")
        if any(verdict != Verdict.NOT_REVIEWED for verdict in self.verdicts) and not self.reviewer:
            raise ValueError("Reviewed criteria require a reviewer")
        return self


def _completed_recommendations(source_json: bytes) -> KnowledgeRecommendations:
    artifact = RecommendationArtifact.model_validate_json(source_json)
    if artifact.status != "completed" or artifact.recommendations is None:
        raise ValueError("Only completed recommendation artifacts can be reviewed")
    return artifact.recommendations


def create_review(source_json: bytes) -> KnowledgeReview:
    """Create a pending template, including explicit review of an abstention."""
    recommendations = _completed_recommendations(source_json)
    return KnowledgeReview(
        schema_version=1,
        source_sha256=sha256(source_json).hexdigest(),
        reviewer="",
        response_appropriateness=Verdict.NOT_REVIEWED,
        limitations=Verdict.NOT_REVIEWED,
        notes="",
        checks=[
            KnowledgeCheckReview(
                check_index=index,
                knowledge_support=Verdict.NOT_REVIEWED,
                evidence_relevance=Verdict.NOT_REVIEWED,
                temporal_correctness=Verdict.NOT_REVIEWED,
                actionability=Verdict.NOT_REVIEWED,
                notes="",
            )
            for index in range(len(recommendations.checks))
        ],
    )


def evaluate_review(source_json: bytes, review_json: bytes) -> ReviewStatus:
    """Summarize explicit judgments bound to one completed source artifact."""
    recommendations = _completed_recommendations(source_json)
    review = KnowledgeReview.model_validate_json(review_json)
    if review.source_sha256 != sha256(source_json).hexdigest():
        raise ValueError("Review belongs to different source bytes")
    indexes = sorted(check.check_index for check in review.checks)
    if indexes != list(range(len(recommendations.checks))):
        raise ValueError("Review checks must exactly match the source recommendations")

    if Verdict.FAIL in review.verdicts:
        return ReviewStatus.FAILED
    if Verdict.NOT_REVIEWED in review.verdicts:
        return ReviewStatus.PENDING
    return ReviewStatus.PASSED
