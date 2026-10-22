from asyncio import to_thread
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from sqlalchemy import Engine

from ai_incident_investigator.investigations.ports import StorageError
from ai_incident_investigator.investigations.router import router as investigations_router
from ai_incident_investigator.settings import get_settings
from ai_incident_investigator.storage.database import create_database_engine
from ai_incident_investigator.storage.repository import SqlAlchemyInvestigationStore
from ai_incident_investigator.storage.usage import SqlAlchemyUsageReader
from ai_incident_investigator.usage.router import router as usage_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    engine: Engine | None = None
    app.state.investigation_store = None
    app.state.usage_reader = None

    try:
        if settings.database_url is not None:
            engine = create_database_engine(settings.database_url)
            store = SqlAlchemyInvestigationStore(engine)
            try:
                await to_thread(store.check_ready)
            except StorageError:
                raise RuntimeError(
                    "Investigation database is unavailable; check connectivity and apply migrations"
                ) from None
            app.state.investigation_store = store
            app.state.usage_reader = SqlAlchemyUsageReader(engine)
        yield
    finally:
        app.state.investigation_store = None
        app.state.usage_reader = None
        if engine is not None:
            await to_thread(engine.dispose)


async def health() -> dict[str, str]:
    return {"status": "UP"}


def create_app() -> FastAPI:
    application = FastAPI(
        title="AI Incident Investigator",
        version=version("ai-incident-investigator"),
        lifespan=lifespan,
    )
    application.include_router(investigations_router)
    application.include_router(usage_router)
    application.add_api_route("/health", health, methods=["GET"], tags=["health"])
    return application


app = create_app()
