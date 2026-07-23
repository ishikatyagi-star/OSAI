from fastapi.testclient import TestClient

from api.main import app


def test_health(monkeypatch) -> None:
    monkeypatch.setenv("OSAI_BUILD_SHA", "portable-build")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "render-build")
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["build_sha"] == "render-build"

    monkeypatch.delenv("RENDER_GIT_COMMIT")
    assert client.get("/health/live").json()["build_sha"] == "portable-build"


def test_integrations_fallback_without_database() -> None:
    client = TestClient(app)
    response = client.get("/integrations")
    assert response.status_code == 200
    # Without a database there is no fixed native-card set: the endpoint returns
    # only live Composio-sourced connections (none when no key is configured, so
    # this is [] in CI). The key property is that nothing is a seeded native
    # "not_configured" card.
    items = response.json()
    assert all(it.get("auth_state") != "not_configured" for it in items)
