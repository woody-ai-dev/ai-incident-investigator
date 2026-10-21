from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ai_incident_investigator.investigations.ports import StorageError
from ai_incident_investigator.usage.models import UsageDashboard, UsageQuery
from ai_incident_investigator.usage.ports import UsageReader

router = APIRouter(prefix="/usage", tags=["usage"])


def get_usage_reader(request: Request) -> UsageReader | None:
    return cast(UsageReader | None, getattr(request.app.state, "usage_reader", None))


@router.get("", response_model=UsageDashboard, summary="Summarize recorded model usage")
def get_usage(
    query: Annotated[UsageQuery, Query()],
    reader: Annotated[UsageReader | None, Depends(get_usage_reader)],
) -> UsageDashboard:
    if reader is None:
        raise HTTPException(status_code=503, detail="Usage storage is not configured")
    try:
        return reader.read(query)
    except StorageError:
        raise HTTPException(status_code=503, detail="Usage storage is unavailable") from None
