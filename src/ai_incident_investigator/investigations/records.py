from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field

from ai_incident_investigator.investigations.reports import InvestigationReport, ReportModel
from ai_incident_investigator.investigations.schemas import InvestigationRequest


class StoredInvestigation(ReportModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    schema_version: Literal[1] = 1
    duration_ms: int = Field(ge=0)
    configured_model: str | None = None
    prompt_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    request: InvestigationRequest
    report: InvestigationReport
