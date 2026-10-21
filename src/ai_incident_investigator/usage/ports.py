from typing import Protocol

from ai_incident_investigator.usage.models import UsageDashboard, UsageQuery


class UsageReader(Protocol):
    def read(self, query: UsageQuery) -> UsageDashboard: ...
