from fastapi.testclient import TestClient

from api.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_integrations_fallback_without_database() -> None:
    client = TestClient(app)
    response = client.get("/integrations")
    assert response.status_code == 200
    # Without a database there are no configured integrations to show; the
    # endpoint degrades to an empty list rather than a fixed native-card set.
    assert response.json() == []
