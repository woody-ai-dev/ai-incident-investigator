from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import AwareDatetime, Field

from ai_incident_investigator.evaluation.dataset import (
    Dataset,
    DatasetModel,
    Scenario,
    fixture_path,
)
from ai_incident_investigator.evaluation.runner import (
    CheckResult,
    RecordedActuatorCollector,
    RecordedMetricsCollector,
    run_scenario,
)
from ai_incident_investigator.investigations.analysis import (
    Analysis,
    AnalysisError,
    AnalysisResult,
    Analyzer,
)
from ai_incident_investigator.investigations.reports import Evidence, InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate
from ai_incident_investigator.llm.prompts import SYSTEM_PROMPT


class LiveCaseResult(DatasetModel):
    scenario_id: str
    repeat: int = Field(ge=1, le=3)
    calls: int = Field(ge=0, le=1)
    duration_ms: int = Field(ge=0)
    report: InvestigationReport | None
    checks: list[CheckResult] = Field(min_length=1)
    review_questions: list[str]
    error: Literal["analysis_failed", "pipeline_failed"] | None = None

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


class LiveEvaluationRun(DatasetModel):
    mode: Literal["live_model"] = "live_model"
    semantic_quality: Literal["pending_manual_review"] = "pending_manual_review"
    provider: Literal["openai"] = "openai"
    model: str = Field(min_length=1, max_length=100)
    prompt_sha256: str
    dataset_sha256: str
    dataset_version: int
    code_revision: str | None = Field(default=None, max_length=100)
    created_at: AwareDatetime
    repeats: int = Field(ge=1, le=3)
    max_calls: int = Field(ge=1, le=10)
    completed: bool = False
    results: list[LiveCaseResult] = Field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return sum(result.calls for result in self.results)

    @property
    def passed(self) -> bool:
        return self.completed and bool(self.results) and all(item.passed for item in self.results)


class CountingAnalyzer:
    """Count analysis attempts, including attempts rejected by the adapter."""

    def __init__(self, delegate: Analyzer) -> None:
        self.delegate = delegate
        self.calls = 0

    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis | AnalysisResult:
        if self.calls:
            raise AnalysisError("Only one analysis attempt is allowed per case")

        self.calls += 1
        return self.delegate.analyze(request, evidence, missing_data)


def dataset_fingerprint(dataset: Dataset, *, fixtures_dir: Path) -> str:
    digest = sha256(dataset.model_dump_json().encode("utf-8"))

    for scenario in dataset.scenarios:
        digest.update(b"\x00" + scenario.log_file.encode("utf-8") + b"\x00")
        digest.update(fixture_path(fixtures_dir, scenario).read_bytes())

    return digest.hexdigest()


def _grade_live_report(
    baseline: InvestigationReport,
    report: InvestigationReport,
    *,
    calls: int,
) -> list[CheckResult]:
    has_evidence = bool(baseline.evidence)
    expected_status = "completed" if has_evidence else "skipped"
    checks = {
        "evidence_preserved": (
            report.evidence == baseline.evidence,
            "All evidence must match the validated offline baseline exactly.",
        ),
        "data_gaps_preserved": (
            all(issue in report.missing_data for issue in baseline.missing_data),
            "Original collection gaps and snapshot limitations must remain visible.",
        ),
        "analysis_status": (
            report.analysis_status == expected_status,
            f"Expected analysis_status={expected_status}.",
        ),
        "analysis_attempts": (
            calls == int(has_evidence),
            "Analyze evidence once and skip the provider when evidence is empty.",
        ),
        "empty_evidence_has_no_conclusions": (
            has_evidence or (not report.findings and not report.hypotheses),
            "An empty evidence set must not produce findings or hypotheses.",
        ),
    }

    return [
        CheckResult(name=name, passed=passed, description=description)
        for name, (passed, description) in checks.items()
    ]


def _run_case(
    scenario: Scenario,
    baseline: InvestigationReport,
    *,
    fixtures_dir: Path,
    analyzer: Analyzer,
    repeat: int,
) -> LiveCaseResult:
    counted = CountingAnalyzer(analyzer)
    started = perf_counter()

    try:
        report = investigate(
            scenario.request,
            log_path=fixture_path(fixtures_dir, scenario),
            metrics_collector=(
                RecordedMetricsCollector(scenario.metrics) if scenario.metrics is not None else None
            ),
            actuator_collector=(
                RecordedActuatorCollector(scenario.actuator)
                if scenario.actuator is not None
                else None
            ),
            analyzer=counted,
        )
    except (OSError, ValueError):
        report = None

    return LiveCaseResult(
        scenario_id=scenario.id,
        repeat=repeat,
        calls=counted.calls,
        duration_ms=round((perf_counter() - started) * 1000),
        report=report,
        checks=(
            _grade_live_report(baseline, report, calls=counted.calls)
            if report is not None
            else [
                CheckResult(
                    name="report_generation",
                    passed=False,
                    description="The investigation pipeline could not produce a report.",
                )
            ]
        ),
        review_questions=scenario.review_questions,
        error=(
            "pipeline_failed"
            if report is None
            else "analysis_failed"
            if report.analysis_status == "failed"
            else None
        ),
    )


def run_live_evaluation(
    dataset: Dataset,
    *,
    fixtures_dir: Path,
    analyzer: Analyzer,
    model: str,
    repeats: int = 1,
    max_calls: int = 3,
    code_revision: str | None = None,
    checkpoint: Callable[[LiveEvaluationRun], None] | None = None,
) -> LiveEvaluationRun:
    if not 1 <= repeats <= 3 or not 1 <= max_calls <= 10:
        raise ValueError("Repeats must be 1..3 and max_calls must be 1..10")

    prepared: list[tuple[Scenario, InvestigationReport]] = []

    for scenario in dataset.scenarios:
        baseline = run_scenario(scenario, fixtures_dir=fixtures_dir)

        if not baseline.passed or baseline.report is None:
            raise ValueError(f"Offline baseline failed for scenario {scenario.id}")

        prepared.append((scenario, baseline.report))

    planned_calls = sum(bool(report.evidence) for _, report in prepared) * repeats

    if planned_calls > max_calls:
        raise ValueError(f"This run needs up to {planned_calls} calls; max_calls={max_calls}")

    run = LiveEvaluationRun(
        model=model,
        prompt_sha256=sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        dataset_sha256=dataset_fingerprint(dataset, fixtures_dir=fixtures_dir),
        dataset_version=dataset.version,
        code_revision=code_revision,
        created_at=datetime.now(UTC),
        repeats=repeats,
        max_calls=max_calls,
    )

    if checkpoint is not None:
        checkpoint(run)

    for repeat in range(1, repeats + 1):
        for scenario, baseline_report in prepared:
            run.results.append(
                _run_case(
                    scenario,
                    baseline_report,
                    fixtures_dir=fixtures_dir,
                    analyzer=analyzer,
                    repeat=repeat,
                )
            )

            if checkpoint is not None:
                checkpoint(run)

    run.completed = True

    if checkpoint is not None:
        checkpoint(run)

    return run
