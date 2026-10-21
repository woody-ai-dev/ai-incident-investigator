from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from ai_incident_investigator.investigations.reports import (
    Evidence,
    Finding,
    Hypothesis,
    RecommendedCheck,
    ReportModel,
    ReportText,
)
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.usage.models import LLMUsage


class Analysis(ReportModel):
    summary: ReportText = Field(
        description=(
            "One main supported observation and its telemetry source, followed only by "
            "the essential uncertainty about cause or impact. Use one or two short sentences. "
            "Put secondary observations, timestamps and metric ranges in findings."
        )
    )
    findings: list[Finding] = Field(max_length=10)
    hypotheses: list[Hypothesis] = Field(max_length=5)
    recommended_checks: list[RecommendedCheck] = Field(min_length=1, max_length=10)


@dataclass(frozen=True)
class AnalysisResult:
    analysis: Analysis
    usage: LLMUsage


class AnalysisError(RuntimeError):
    """The analyzer could not produce a usable result."""

    def __init__(self, message: str, *, usage: LLMUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class Analyzer(Protocol):
    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis | AnalysisResult: ...
