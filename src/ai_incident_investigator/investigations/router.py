from fastapi import APIRouter, status

from ai_incident_investigator.investigations.reports import InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.post(
    "",
    response_model=InvestigationReport,
    status_code=status.HTTP_200_OK,
    summary="Investigate a service incident",
)
def create_investigation(request: InvestigationRequest) -> InvestigationReport:
    return investigate(request)
