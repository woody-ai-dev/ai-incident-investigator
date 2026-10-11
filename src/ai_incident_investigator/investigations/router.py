from typing import Annotated

from fastapi import APIRouter, Depends, status

from ai_incident_investigator.investigations.analysis import Analyzer
from ai_incident_investigator.investigations.reports import InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.service import investigate
from ai_incident_investigator.llm.dependencies import get_analyzer
from ai_incident_investigator.settings import Settings, get_settings
from ai_incident_investigator.sources.dependencies import get_metrics_collector
from ai_incident_investigator.sources.metrics import MetricsCollector

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.post(
    "",
    response_model=InvestigationReport,
    status_code=status.HTTP_200_OK,
    summary="Investigate a service incident",
)
def create_investigation(
    request: InvestigationRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    metrics_collector: Annotated[MetricsCollector | None, Depends(get_metrics_collector)],
    analyzer: Annotated[Analyzer | None, Depends(get_analyzer)],
) -> InvestigationReport:
    return investigate(
        request,
        log_path=settings.log_path,
        metrics_collector=metrics_collector,
        analyzer=analyzer,
    )
