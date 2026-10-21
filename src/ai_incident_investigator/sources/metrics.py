from typing import Protocol

from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.sources.collection import CollectionResult


class MetricsCollection(CollectionResult):
    pass


class MetricsCollector(Protocol):
    def collect(self, request: InvestigationRequest) -> MetricsCollection: ...
