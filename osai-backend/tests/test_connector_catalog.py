"""Full-catalog Composio browsing and connected integration cards."""

from __future__ import annotations

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from connectors.composio_tool import ComposioClient
from db.models import Base, ConnectorAccount, ConnectorRecord
from db.session import get_db

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


async def test_api_catalog_delegates_to_composio(monkeypatch):
    from api.routes import composio

    class _ConfiguredClient:
        def available(self):
            return True

        async def list_toolkits(self, **kwargs):
            assert kwargs == {"search": "git", "cursor": "next", "limit": 10}
            return {"items": [{"slug": "github"}], "next_cursor": None}

    monkeypatch.setattr(composio, "get_default_composio_client", lambda: _ConfiguredClient())

    page = await composio.list_toolkits(search="git", cursor="next", limit=10)
    assert page == {"items": [{"slug": "github"}], "next_cursor": None}


async def test_connect_allows_action_only_composio_toolkits(monkeypatch):
    from api.routes import composio

    class _ConfiguredClient:
        def available(self):
            return True

        async def connect(self, toolkit, org_id, callback_url=None):
            return {"redirect_url": f"https://composio.test/{toolkit}/{org_id}"}

    monkeypatch.setattr(composio, "get_default_composio_client", lambda: _ConfiguredClient())
    result = await composio.connect(
        "github",
        "demo-org",
        {"sub": "admin-1", "org_id": "demo-org"},
    )
    assert result["redirect_url"].endswith("/github/demo-org")


async def test_composio_connections_become_integration_cards(monkeypatch):
    from api.routes import integrations as integrations_route

    class _FakeComposio:
        def available(self):
            return True

        async def list_connections(self, org_id):
            return [
                {"id": "ca_1", "toolkit": "gmail", "status": "ACTIVE", "email": "a@b.com"},
                {"id": "ca_2", "toolkit": "googledrive", "status": "ACTIVE", "email": None},
                {"id": "ca_3", "toolkit": "zoom", "status": "ACTIVE", "email": None},
            ]

    monkeypatch.setattr(
        integrations_route, "get_default_composio_client", lambda: _FakeComposio()
    )

    from fastapi.testclient import TestClient

    from api.main import app

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        ConnectorRecord(
            key="google_drive",
            display_name="Google Drive",
            capabilities=["sync", "search"],
        )
    )
    session.add(
        ConnectorAccount(
            org_id="demo-org",
            connector_key="google_drive",
            auth_state="not_configured",
        )
    )
    session.add(
        ConnectorRecord(
            key="freshdesk",
            display_name="Freshdesk",
            capabilities=["sync", "search", "execute"],
        )
    )
    session.add(
        ConnectorAccount(
            org_id="demo-org",
            connector_key="freshdesk",
            auth_state="connected",
        )
    )
    session.add(ConnectorRecord(key="zoom", display_name="Zoom", capabilities=["sync"]))
    session.add(
        ConnectorAccount(
            org_id="demo-org",
            connector_key="zoom",
            auth_state="connected",
        )
    )
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        resp = TestClient(app).get("/integrations")
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
    assert resp.status_code == 200
    items = {it["key"]: it for it in resp.json()}

    assert items["google_drive"]["auth_state"] == "connected"
    assert items["google_drive"]["source"] == "composio"
    assert items["gmail"]["auth_state"] == "connected"
    assert items["gmail"]["account_email"] == "a@b.com"
    assert items["gmail"]["source"] == "composio"
    assert items["gmail"]["capabilities"] == ["sync", "search"]
    assert "freshdesk" not in items
    assert "zoom" not in items
    assert all("logo" not in item for item in items.values())
