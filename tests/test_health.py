from fastapi.testclient import TestClient

from ai_incident_investigator.main import app


def test_health_returns_up() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP"}
