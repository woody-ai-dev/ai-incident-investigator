from typing import Protocol

from pydantic import BaseModel, Field

from ai_incident_investigator.investigations.reports import Evidence
from ai_incident_investigator.investigations.schemas import InvestigationRequest


class MetricsCollection(BaseModel):
    evidence: list[Evidence] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class MetricsCollector(Protocol):
    def collect(self, request: InvestigationRequest) -> MetricsCollection: ...
