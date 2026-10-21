from typing import Protocol
from uuid import UUID

from ai_incident_investigator.investigations.history import InvestigationPage, InvestigationQuery
from ai_incident_investigator.investigations.records import StoredInvestigation


class StorageError(RuntimeError):
    """The configured investigation store could not complete an operation."""


class InvestigationWriter(Protocol):
    def save(self, record: StoredInvestigation) -> None: ...


class InvestigationStore(InvestigationWriter, Protocol):
    def get(self, investigation_id: UUID) -> StoredInvestigation | None: ...

    def list_investigations(self, query: InvestigationQuery) -> InvestigationPage: ...
