from typing import Protocol
from uuid import UUID

from ai_incident_investigator.investigations.records import StoredInvestigation


class StorageError(RuntimeError):
    """The configured investigation store could not complete an operation."""


class InvestigationStore(Protocol):
    def save(self, record: StoredInvestigation) -> None: ...

    def get(self, investigation_id: UUID) -> StoredInvestigation | None: ...
