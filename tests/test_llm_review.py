from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_incident_investigator.evaluation.live import LiveCaseResult, LiveEvaluationRun
from ai_incident_investigator.evaluation.review import (
    ReviewStatus,
    RunReview,
    create_review,
    evaluate_review,
    load_run,
)
from ai_incident_investigator.evaluation.runner import CheckResult
from ai_incident_investigator.investigations.reports import (
    Evidence,
    EvidenceSource,
    InvestigationReport,
)

CRITERIA = ("evidence_support", "causal_reasoning", "data_limitations", "next_checks")


@pytest.fixture
def saved_run(tmp_path: Path) -> Path:
    evidence = Evidence(
        id="metric-up",
        source=EvidenceSource.METRIC,
        service="order-service",
        summary="One successful scrape observation; business health is unknown.",
        reference="fixture:up",
        start_time=datetime(2026, 10, 16, 10, tzinfo=UTC),
        end_time=datetime(2026, 10, 16, 10, 1, tzinfo=UTC),
    )
    report = InvestigationReport(
        analysis_status="completed",
        summary="The scrape succeeded at an observed evaluation point.",
        evidence=[evidence],
        findings=[],
        hypotheses=[],
        recommended_checks=[],
        missing_data=["Business operations have not been checked."],
    )
    run = LiveEvaluationRun(
        model="test-model",
        prompt_sha256="a" * 64,
        dataset_sha256="b" * 64,
        dataset_version=1,
        created_at=datetime(2026, 10, 16, 10, 2, tzinfo=UTC),
        repeats=1,
        max_calls=3,
        completed=True,
        results=[
            LiveCaseResult(
                scenario_id="scrape-only",
                repeat=1,
                calls=1,
                duration_ms=1,
                report=report,
                checks=[CheckResult(name="test-contract", passed=True, description="Fixture")],
                review_questions=["Does the report avoid claiming business availability?"],
            ),
            LiveCaseResult(
                scenario_id="empty-evidence",
                repeat=1,
                calls=0,
                duration_ms=0,
                report=report.model_copy(update={"analysis_status": "skipped", "evidence": []}),
                checks=[CheckResult(name="test-contract", passed=True, description="Fixture")],
                review_questions=["Was model analysis skipped?"],
            ),
        ],
    )
    path = tmp_path / "run.json"
    path.write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def approved_review(run: LiveEvaluationRun, fingerprint: str) -> RunReview:
    payload = create_review(run, source_sha256=fingerprint).model_dump(mode="json")
    payload["reviewer"] = "Test reviewer"
    for case in payload["cases"]:
        for criterion in CRITERIA:
            case[criterion] = "pass"
        case["notes"] = "The fixture only reports the observed scrape and leaves the cause unknown."
    return RunReview.model_validate(payload)


def test_template_is_pending_and_excludes_skipped_case(saved_run: Path) -> None:
    run, fingerprint = load_run(saved_run)
    before = run.model_dump_json()
    review = create_review(run, source_sha256=fingerprint)

    assert len(review.cases) == 1
    assert review.cases[0].scenario_id == "scrape-only"
    assert evaluate_review(run, review, source_sha256=fingerprint) == ReviewStatus.PENDING
    assert run.model_dump_json() == before


def test_review_pass_is_separate_from_original_run(saved_run: Path) -> None:
    run, fingerprint = load_run(saved_run)
    review = approved_review(run, fingerprint)

    assert evaluate_review(run, review, source_sha256=fingerprint) == ReviewStatus.PASSED
    assert run.semantic_quality == "pending_manual_review"


@pytest.mark.parametrize("criterion", CRITERIA)
@pytest.mark.parametrize(
    ("verdict", "expected"),
    [("fail", ReviewStatus.FAILED), ("not_reviewed", ReviewStatus.PENDING)],
)
def test_each_criterion_can_block_approval(
    saved_run: Path, criterion: str, verdict: str, expected: ReviewStatus
) -> None:
    run, fingerprint = load_run(saved_run)
    payload = approved_review(run, fingerprint).model_dump(mode="json")
    payload["cases"][0][criterion] = verdict
    payload["cases"][0]["notes"] = "A reviewer must check that scrape success is not called uptime."
    review = RunReview.model_validate(payload)

    assert run.passed
    assert evaluate_review(run, review, source_sha256=fingerprint) == expected


@pytest.mark.parametrize(
    "mutation",
    ["blank-reviewer", "blank-notes", "missing-criterion", "unknown-criterion", "duplicate-case"],
)
def test_invalid_review_is_rejected(saved_run: Path, mutation: str) -> None:
    run, fingerprint = load_run(saved_run)
    payload = approved_review(run, fingerprint).model_dump(mode="json")
    if mutation == "blank-reviewer":
        payload["reviewer"] = "  "
    elif mutation == "blank-notes":
        payload["cases"][0]["notes"] = "  "
    elif mutation == "missing-criterion":
        del payload["cases"][0]["evidence_support"]
    elif mutation == "unknown-criterion":
        payload["cases"][0]["extra"] = "pass"
    else:
        payload["cases"].append(payload["cases"][0])

    with pytest.raises(ValueError):
        RunReview.model_validate(payload)


def test_review_case_must_belong_to_source(saved_run: Path) -> None:
    run, fingerprint = load_run(saved_run)
    payload = approved_review(run, fingerprint).model_dump(mode="json")
    payload["cases"][0]["scenario_id"] = "another-scenario"

    with pytest.raises(ValueError, match="exactly match"):
        evaluate_review(run, RunReview.model_validate(payload), source_sha256=fingerprint)


def test_changed_source_bytes_invalidate_review(saved_run: Path) -> None:
    run, fingerprint = load_run(saved_run)
    review = approved_review(run, fingerprint)
    saved_run.write_bytes(saved_run.read_bytes() + b"\n")
    changed_run, changed_fingerprint = load_run(saved_run)

    with pytest.raises(ValueError, match="different source bytes"):
        evaluate_review(changed_run, review, source_sha256=changed_fingerprint)


@pytest.mark.parametrize(
    "mutation",
    ["unfinished", "failed-check", "case-error", "wrong-calls", "missing-repeat", "invalid-skip"],
)
def test_technical_failure_cannot_be_approved(saved_run: Path, mutation: str) -> None:
    run, fingerprint = load_run(saved_run)
    if mutation == "unfinished":
        run.completed = False
    elif mutation == "failed-check":
        run.results[0].checks[0].passed = False
    elif mutation == "case-error":
        run.results[0].error = "analysis_failed"
    elif mutation == "wrong-calls":
        run.results[0].calls = 0
    elif mutation == "invalid-skip":
        run.results[1].report = run.results[0].report
        assert run.results[1].report is not None
        run.results[1].report = run.results[1].report.model_copy(
            update={"analysis_status": "skipped"}
        )
    else:
        run.repeats = 2
    review = approved_review(run, fingerprint)

    assert evaluate_review(run, review, source_sha256=fingerprint) == ReviewStatus.TECHNICAL_FAILURE


def test_empty_analysis_set_cannot_vacuously_pass(saved_run: Path) -> None:
    run, fingerprint = load_run(saved_run)
    run.results = [run.results[1]]

    with pytest.raises(ValueError, match="no completed model analyses"):
        create_review(run, source_sha256=fingerprint)


def test_duplicate_source_cases_are_rejected(saved_run: Path) -> None:
    run, fingerprint = load_run(saved_run)
    run.results.append(run.results[0].model_copy(deep=True))

    with pytest.raises(ValueError, match="duplicate case keys"):
        create_review(run, source_sha256=fingerprint)


@pytest.mark.parametrize("mutation", ["missing-review", "extra-review", "call-budget"])
def test_multi_case_review_requires_exact_coverage_and_budget(
    saved_run: Path, mutation: str
) -> None:
    run, fingerprint = load_run(saved_run)
    second = run.results[0].model_copy(deep=True)
    second.scenario_id = "another-scenario"
    run.results.append(second)
    payload = approved_review(run, fingerprint).model_dump(mode="json")

    if mutation == "call-budget":
        run.max_calls = 1
        result = evaluate_review(run, RunReview.model_validate(payload), source_sha256=fingerprint)
        assert result == ReviewStatus.TECHNICAL_FAILURE
        return

    if mutation == "missing-review":
        payload["cases"].pop()
    else:
        extra = payload["cases"][0].copy()
        extra["scenario_id"] = "unknown-scenario"
        payload["cases"].append(extra)

    with pytest.raises(ValueError, match="exactly match"):
        evaluate_review(run, RunReview.model_validate(payload), source_sha256=fingerprint)


def test_review_is_revalidated_after_in_memory_mutation(saved_run: Path) -> None:
    run, fingerprint = load_run(saved_run)
    review = approved_review(run, fingerprint)
    review.reviewer = ""

    with pytest.raises(ValueError, match="require a reviewer"):
        evaluate_review(run, review, source_sha256=fingerprint)
