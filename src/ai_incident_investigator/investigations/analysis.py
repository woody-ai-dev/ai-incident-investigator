from collections.abc import Sequence
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


class Analysis(ReportModel):
    summary: ReportText
    findings: list[Finding] = Field(max_length=10)
    hypotheses: list[Hypothesis] = Field(max_length=5)
    recommended_checks: list[RecommendedCheck] = Field(min_length=1, max_length=10)


class AnalysisError(RuntimeError):
    """The analyzer could not produce a usable result."""


class Analyzer(Protocol):
    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis: ...
