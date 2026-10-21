import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ai_incident_investigator.dependencies import (
    get_actuator_collector,
    get_analysis_configuration,
    get_analyzer,
    get_investigation_store,
    get_metrics_collector,
)
from ai_incident_investigator.investigations.analysis import Analyzer
from ai_incident_investigator.investigations.history import InvestigationPage, InvestigationQuery
from ai_incident_investigator.investigations.ports import InvestigationStore, StorageError
from ai_incident_investigator.investigations.records import StoredInvestigation
from ai_incident_investigator.investigations.reports import InvestigationReport
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.investigations.workflow import (
    AnalysisConfiguration,
    execute_investigation,
)
from ai_incident_investigator.settings import Settings, get_settings
from ai_incident_investigator.sources.context import ActuatorCollector
from ai_incident_investigator.sources.metrics import MetricsCollector

router = APIRouter(prefix="/investigations", tags=["investigations"])
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=InvestigationReport,
    status_code=status.HTTP_200_OK,
    summary="Investigate a service incident",
)
def create_investigation(
    request: InvestigationRequest,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    metrics_collector: Annotated[MetricsCollector | None, Depends(get_metrics_collector)],
    actuator_collector: Annotated[
        ActuatorCollector | None,
        Depends(get_actuator_collector),
    ],
    analyzer: Annotated[Analyzer | None, Depends(get_analyzer)],
    store: Annotated[InvestigationStore | None, Depends(get_investigation_store)],
    analysis_configuration: Annotated[AnalysisConfiguration, Depends(get_analysis_configuration)],
) -> InvestigationReport:
    try:
        execution = execute_investigation(
            request,
            log_path=settings.log_path,
            metrics_collector=metrics_collector,
            actuator_collector=actuator_collector,
            analyzer=analyzer,
            store=store,
            analysis_configuration=analysis_configuration,
        )
    except StorageError as exc:
        logger.warning("Investigation storage failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Investigation could not be saved") from None
    if execution.investigation_id is not None:
        response.headers["X-Investigation-ID"] = str(execution.investigation_id)
    return execution.report


@router.get("", response_model=InvestigationPage, summary="List saved investigations")
def list_investigations(
    query: Annotated[InvestigationQuery, Query()],
    store: Annotated[InvestigationStore | None, Depends(get_investigation_store)],
) -> InvestigationPage:
    if store is None:
        raise HTTPException(status_code=503, detail="Investigation storage is not configured")
    try:
        return store.list_investigations(query)
    except StorageError as exc:
        logger.warning("Investigation history failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503, detail="Investigation storage is unavailable"
        ) from None


@router.get(
    "/{investigation_id}",
    response_model=StoredInvestigation,
    summary="Get a saved investigation",
)
def get_investigation(
    investigation_id: UUID,
    store: Annotated[InvestigationStore | None, Depends(get_investigation_store)],
) -> StoredInvestigation:
    if store is None:
        raise HTTPException(status_code=503, detail="Investigation storage is not configured")
    try:
        record = store.get(investigation_id)
    except StorageError as exc:
        logger.warning("Investigation storage failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503, detail="Investigation storage is unavailable"
        ) from None
    if record is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return record
