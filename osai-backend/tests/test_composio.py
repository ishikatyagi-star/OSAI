"""Live Composio adapter tests. Skip unless OSAI_COMPOSIO_API_KEY is configured."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from connectors.composio_tool import ComposioClient

client = TestClient(app)


def _client_or_skip() -> ComposioClient:
    cl = ComposioClient()
    if not cl.available():
        pytest.skip("OSAI_COMPOSIO_API_KEY not set")
    return cl


async def test_composio_list_tools_maps_to_specs():
    client = _client_or_skip()
    specs = await client.list_tools(["composio_search"], limit=5)
    assert len(specs) >= 1
    for spec in specs:
        assert {"name", "tool", "action", "description", "parameters", "provider"} <= spec.keys()
        assert spec["provider"] == "composio"
        assert spec["parameters"]["type"] == "object"


async def test_composio_execute_no_auth_search():
    client = _client_or_skip()
    result = await client.execute(
        "COMPOSIO_SEARCH_DUCK_DUCK_GO_SEARCH",
        {"query": "OSAI university operations"},
        user_id="demo-org",
    )
    assert result["successful"] is True
    assert result["data"] is not None


def test_composio_toolkits_endpoint():
    _client_or_skip()
    resp = client.get("/integrations/composio/toolkits")
    assert resp.status_code == 200
    page = resp.json()
    assert len(page["items"]) >= 1
    assert all("slug" in t for t in page["items"])


def test_composio_toolkits_search():
    _client_or_skip()
    resp = client.get("/integrations/composio/toolkits", params={"search": "gmail"})
    assert resp.status_code == 200
    slugs = [t["slug"] for t in resp.json()["items"]]
    assert any("gmail" in s for s in slugs)
