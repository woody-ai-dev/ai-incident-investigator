from fastapi import FastAPI

from ai_incident_investigator.investigations.router import router as investigations_router

app = FastAPI(
    title="AI Incident Investigator",
    version="0.1.0",
)

app.include_router(investigations_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "UP"}
