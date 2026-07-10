from fastapi.testclient import TestClient

from api.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code in {200, 503}
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert {"database", "qdrant", "redis"} <= body["checks"].keys()


def test_integrations_fallback_without_database() -> None:
    client = TestClient(app)
    response = client.get("/integrations")
    assert response.status_code == 200
    keys = {item["key"] for item in response.json()}
    assert {"notion", "slack", "freshdesk", "google_drive"}.issubset(keys)
