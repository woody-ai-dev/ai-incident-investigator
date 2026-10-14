from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field

from ai_incident_investigator.evaluation.dataset import (
    Dataset,
    DatasetModel,
    Scenario,
    fixture_path,
)
from ai_incident_investigator.investigations.reports import (
    Evidence,
    EvidenceSource,
    InvestigationReport,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate
from ai_incident_investigator.sources.context import ActuatorCollection
from ai_incident_investigator.sources.metrics import MetricsCollection


class RecordedMetricsCollector:
    def __init__(self, snapshot: MetricsCollection) -> None:
        self.snapshot = snapshot

    def collect(self, request: InvestigationRequest) -> MetricsCollection:
        return self.snapshot.model_copy(deep=True)


class RecordedActuatorCollector:
    def __init__(self, snapshot: ActuatorCollection) -> None:
        self.snapshot = snapshot

    def collect(self, request: InvestigationRequest) -> ActuatorCollection:
        return self.snapshot.model_copy(deep=True)


class CheckResult(DatasetModel):
    name: str
    passed: bool
    description: str


class ScenarioResult(DatasetModel):
    scenario_id: str
    checks: list[CheckResult] = Field(min_length=1)
    report: InvestigationReport | None

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


class EvaluationRun(DatasetModel):
    mode: Literal["offline_pipeline"] = "offline_pipeline"
    semantic_quality: Literal["not_evaluated"] = "not_evaluated"

    dataset_version: int
    created_at: AwareDatetime
    scenarios: list[ScenarioResult] = Field(min_length=1)

    @property
    def passed_scenarios(self) -> int:
        return sum(result.passed for result in self.scenarios)

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.scenarios)


def grade_report(scenario: Scenario, report: InvestigationReport) -> list[CheckResult]:
    request = scenario.request

    recorded: list[Evidence] = []

    for collection in (scenario.metrics, scenario.actuator):
        if collection is not None:
            recorded.extend(collection.evidence)

    actual_recorded = [
        item
        for item in report.evidence
        if item.source in (EvidenceSource.METRIC, EvidenceSource.ACTUATOR)
    ]

    historical = [
        item
        for item in report.evidence
        if item.source in (EvidenceSource.LOG, EvidenceSource.METRIC)
    ]

    actual_logs = [item for item in report.evidence if item.source == EvidenceSource.LOG]

    expected_ids = {item.id for item in [*scenario.expected.log_evidence, *recorded]}

    checks = {
        "analysis_disabled": (
            report.analysis_status == "not_requested",
            "Offline evaluation must not run LLM analysis.",
        ),
        "evidence_ids": (
            {item.id for item in report.evidence} == expected_ids,
            "Evidence IDs must exactly match scenario expectations.",
        ),
        "logs_preserved": (
            actual_logs == scenario.expected.log_evidence,
            "Log observations must match the manually reviewed fixture expectations.",
        ),
        "service_identity": (
            all(item.service == request.service for item in report.evidence),
            "All observations must belong to the requested service.",
        ),
        "historical_window": (
            all(
                request.start_time <= item.start_time < request.end_time
                and (item.end_time is None or item.end_time <= request.end_time)
                for item in historical
            ),
            "Log and metric observation times must fit the requested incident window.",
        ),
        "recorded_observations": (
            actual_recorded == recorded,
            "Recorded metrics and Actuator snapshots must remain unchanged.",
        ),
        "data_gaps": (
            all(
                any(fragment in issue for issue in report.missing_data)
                for fragment in scenario.expected.missing_data_contains
            ),
            "Expected collection gaps and snapshot limitations must remain visible.",
        ),
        "no_generated_conclusions": (
            not report.findings and not report.hypotheses,
            "With analysis disabled, findings and hypotheses must remain empty.",
        ),
    }

    return [
        CheckResult(
            name=name,
            passed=passed,
            description=description,
        )
        for name, (passed, description) in checks.items()
    ]


def run_scenario(
    scenario: Scenario,
    *,
    fixtures_dir: Path,
) -> ScenarioResult:
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
            analyzer=None,
        )
    except (OSError, ValueError) as exc:
        return ScenarioResult(
            scenario_id=scenario.id,
            checks=[
                CheckResult(
                    name="report_generation",
                    passed=False,
                    description=(f"Report generation failed ({type(exc).__name__})."),
                )
            ],
            report=None,
        )

    return ScenarioResult(
        scenario_id=scenario.id,
        checks=grade_report(scenario, report),
        report=report,
    )


def run_evaluation(
    dataset: Dataset,
    *,
    fixtures_dir: Path,
) -> EvaluationRun:
    return EvaluationRun(
        dataset_version=dataset.version,
        created_at=datetime.now(UTC),
        scenarios=[
            run_scenario(
                scenario,
                fixtures_dir=fixtures_dir,
            )
            for scenario in dataset.scenarios
        ],
    )
