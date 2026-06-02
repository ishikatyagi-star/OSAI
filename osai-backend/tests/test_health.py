from fastapi.testclient import TestClient

from api.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_integrations_falls_back_without_database() -> None:
    client = TestClient(app)
    response = client.get("/integrations")
    assert response.status_code == 200
    keys = {integration["key"] for integration in response.json()}
    assert {"notion", "slack", "freshdesk", "google_drive"}.issubset(keys)
