from collections import defaultdict
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_incident_investigator.evaluation.live import LiveEvaluationRun


class Verdict(StrEnum):
    NOT_REVIEWED = "not_reviewed"
    PASS = "pass"
    FAIL = "fail"


class ReviewStatus(StrEnum):
    PENDING = "pending_review"
    PASSED = "reviewed_pass"
    FAILED = "reviewed_fail"
    TECHNICAL_FAILURE = "technical_failure"


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CaseReview(ReviewModel):
    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    repeat: int = Field(ge=1, le=3)
    evidence_support: Verdict
    causal_reasoning: Verdict
    data_limitations: Verdict
    next_checks: Verdict
    notes: str = Field(max_length=4000)

    @property
    def key(self) -> tuple[str, int]:
        return self.scenario_id, self.repeat

    @property
    def verdicts(self) -> tuple[Verdict, ...]:
        return (
            self.evidence_support,
            self.causal_reasoning,
            self.data_limitations,
            self.next_checks,
        )

    @model_validator(mode="after")
    def require_review_notes(self) -> Self:
        if any(value != Verdict.NOT_REVIEWED for value in self.verdicts) and not self.notes:
            raise ValueError("Reviewed criteria require explanatory notes")
        return self


class RunReview(ReviewModel):
    schema_version: Literal[1]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer: str = Field(max_length=100)
    cases: list[CaseReview] = Field(min_length=1, max_length=150)

    @model_validator(mode="after")
    def validate_cases_and_reviewer(self) -> Self:
        keys = [case.key for case in self.cases]
        if len(keys) != len(set(keys)):
            raise ValueError("Review case keys must be unique")

        has_decisions = any(
            verdict != Verdict.NOT_REVIEWED for case in self.cases for verdict in case.verdicts
        )
        if has_decisions and not self.reviewer:
            raise ValueError("Reviewed criteria require a reviewer")
        return self


def load_run(path: Path) -> tuple[LiveEvaluationRun, str]:
    """Parse and fingerprint the same saved bytes without calling a model."""
    payload = path.read_bytes()
    return LiveEvaluationRun.model_validate_json(payload), sha256(payload).hexdigest()


def _reviewable_keys(run: LiveEvaluationRun) -> set[tuple[str, int]]:
    keys = [(case.scenario_id, case.repeat) for case in run.results]
    if len(keys) != len(set(keys)):
        raise ValueError("Source run contains duplicate case keys")
    if any(case.repeat > run.repeats for case in run.results):
        raise ValueError("Source case repeat exceeds the run repeat count")

    reviewable = {
        (case.scenario_id, case.repeat)
        for case in run.results
        if case.report is not None and case.report.analysis_status == "completed"
    }
    if not reviewable:
        raise ValueError("Source run has no completed model analyses to review")
    return reviewable


def create_review(run: LiveEvaluationRun, *, source_sha256: str) -> RunReview:
    """Create an unreviewed template; never infer a semantic pass."""
    return RunReview(
        schema_version=1,
        source_sha256=source_sha256,
        reviewer="",
        cases=[
            CaseReview(
                scenario_id=scenario_id,
                repeat=repeat,
                evidence_support=Verdict.NOT_REVIEWED,
                causal_reasoning=Verdict.NOT_REVIEWED,
                data_limitations=Verdict.NOT_REVIEWED,
                next_checks=Verdict.NOT_REVIEWED,
                notes="",
            )
            for scenario_id, repeat in sorted(_reviewable_keys(run))
        ],
    )


def _technical_checks_passed(run: LiveEvaluationRun) -> bool:
    if not run.passed or run.total_calls > run.max_calls:
        return False

    repeats_by_scenario: defaultdict[str, set[int]] = defaultdict(set)
    for case in run.results:
        repeats_by_scenario[case.scenario_id].add(case.repeat)
        report = case.report
        if case.error is not None or report is None:
            return False

        if report.analysis_status == "completed":
            if not report.evidence or case.calls != 1:
                return False
        elif report.analysis_status == "skipped":
            if report.evidence or case.calls or report.findings or report.hypotheses:
                return False
        else:
            return False

    expected_repeats = set(range(1, run.repeats + 1))
    return all(repeats == expected_repeats for repeats in repeats_by_scenario.values())


def evaluate_review(
    run: LiveEvaluationRun,
    review: RunReview,
    *,
    source_sha256: str,
) -> ReviewStatus:
    """Combine saved technical checks with explicitly recorded reviewer judgments."""
    review = RunReview.model_validate(review.model_dump())
    if review.source_sha256 != source_sha256:
        raise ValueError("Review belongs to different source bytes")
    if {case.key for case in review.cases} != _reviewable_keys(run):
        raise ValueError("Review cases must exactly match completed model analyses")

    if not _technical_checks_passed(run):
        return ReviewStatus.TECHNICAL_FAILURE

    verdicts = [verdict for case in review.cases for verdict in case.verdicts]
    if Verdict.FAIL in verdicts:
        return ReviewStatus.FAILED
    if Verdict.NOT_REVIEWED in verdicts:
        return ReviewStatus.PENDING
    return ReviewStatus.PASSED
