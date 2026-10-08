from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ai_incident_investigator.investigations.router import router as investigations_router
from ai_incident_investigator.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    get_settings()
    yield


app = FastAPI(
    title="AI Incident Investigator",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(investigations_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "UP"}
