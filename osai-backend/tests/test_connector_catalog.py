"""Full-catalog connector browsing: toolkit search/pagination and surfacing
non-native Composio connections as integration cards (mocked Composio)."""

from __future__ import annotations

import httpx

from connectors.composio_tool import ComposioClient

_CATALOG = {
    "items": [
        {
            "slug": "gmail",
            "name": "Gmail",
            "auth_schemes": ["OAUTH2"],
            "meta": {"tools_count": 21, "logo": "https://logo/gmail.png", "categories": []},
        },
        {
            "slug": "github",
            "name": "GitHub",
            "auth_schemes": ["OAUTH2"],
            "meta": {"tools_count": 40, "logo": None, "categories": [{"name": "Dev"}]},
        },
    ],
    "next_cursor": "abc123",
}


def _mock_transport(capture: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        capture["params"] = dict(request.url.params)
        return httpx.Response(200, json=_CATALOG)

    return httpx.MockTransport(handler)


async def test_list_toolkits_passes_search_and_cursor(monkeypatch):
    capture: dict = {}
    transport = _mock_transport(capture)
    real_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)
    client = ComposioClient(api_key="test-key")
    page = await client.list_toolkits(search="git", cursor="abc123", limit=10)

    assert capture["params"]["search"] == "git"
    assert capture["params"]["cursor"] == "abc123"
    # Local narrowing keeps only matches even if the provider ignores `search`.
    assert [t["slug"] for t in page["items"]] == ["github"]
    assert page["next_cursor"] == "abc123"


async def test_list_toolkits_returns_page_shape(monkeypatch):
    capture: dict = {}
    transport = _mock_transport(capture)
    real_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)
    client = ComposioClient(api_key="test-key")
    page = await client.list_toolkits()

    assert {t["slug"] for t in page["items"]} == {"gmail", "github"}
    gmail = next(t for t in page["items"] if t["slug"] == "gmail")
    assert gmail["tools_count"] == 21
    assert gmail["no_auth"] is False


async def test_non_native_connection_becomes_integration_card(monkeypatch):
    """An active Composio connection with no native counterpart (e.g. Gmail)
    must show up as its own card in GET /integrations."""
    from api.routes import integrations as integrations_route

    class _FakeComposio:
        def available(self):
            return True

        async def list_connections(self, org_id):
            return [
                {"id": "ca_1", "toolkit": "gmail", "status": "ACTIVE", "email": "a@b.com"},
                {"id": "ca_2", "toolkit": "googledrive", "status": "ACTIVE", "email": None},
            ]

    monkeypatch.setattr(
        integrations_route, "get_default_composio_client", lambda: _FakeComposio()
    )

    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    resp = client.get("/integrations")
    assert resp.status_code == 200
    items = {it["key"]: it for it in resp.json()}

    # Native card overlaid as connected.
    assert items["google_drive"]["auth_state"] == "connected"
    # Non-native toolkit synthesized as its own connected card.
    assert items["gmail"]["auth_state"] == "connected"
    assert items["gmail"]["account_email"] == "a@b.com"
    assert items["gmail"]["source"] == "composio"
