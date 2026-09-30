from fastapi.params import Depends
from typing import Annotated

from fastapi import APIRouter, status

from ai_incident_investigator.investigations.reports import InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate
from ai_incident_investigator.settings import Settings, get_settings

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.post(
    "",
    response_model=InvestigationReport,
    status_code=status.HTTP_200_OK,
    summary="Investigate a service incident",
)
def create_investigation(
    request: InvestigationRequest, settings: Annotated[Settings, Depends(get_settings)]
) -> InvestigationReport:
    return investigate(request, log_path=settings.log_path)
