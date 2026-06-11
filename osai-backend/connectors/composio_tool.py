"""Composio adapter — exposes Composio's tool catalog through OSAI's agent.

Composio (https://composio.dev) provides 1000+ tool integrations with auth
handled for us. We hit its v3 REST API directly (httpx) and map each tool's
`input_parameters` (already a JSON schema) into the same tool-spec shape the
agent uses for native connectors. `no_auth` tools (e.g. web search) execute
immediately; OAuth tools need a connected account per user/org.

Gated by `settings.composio_api_key`: unset -> `available()` is False and the
agent simply has no Composio tools.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger("osai.composio")


class ComposioClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or settings.composio_api_key
        self.base_url = (base_url or settings.composio_base_url).rstrip("/")

    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key or "", "Content-Type": "application/json"}

    async def list_tools(
        self, toolkits: list[str] | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return Composio tools mapped into OSAI agent tool-spec format."""
        toolkits = toolkits or settings.composio_toolkit_list
        specs: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30) as client:
            for toolkit in toolkits:
                resp = await client.get(
                    f"{self.base_url}/api/v3/tools",
                    headers=self._headers(),
                    params={"toolkit_slug": toolkit, "limit": limit},
                )
                if resp.status_code != 200:
                    logger.warning("Composio list_tools %s -> %s", toolkit, resp.status_code)
                    continue
                for tool in resp.json().get("items", []):
                    specs.append(_to_spec(tool))
        return specs

    async def execute(
        self, slug: str, arguments: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        """Execute a Composio tool. Returns {successful, data, error}."""
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/api/v3/tools/execute/{slug}",
                headers=self._headers(),
                json={"arguments": arguments, "user_id": user_id},
            )
        if resp.status_code != 200:
            return {
                "successful": False,
                "data": None,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        body = resp.json()
        return {
            "successful": body.get("successful", body.get("error") is None),
            "data": body.get("data"),
            "error": body.get("error"),
        }


def _to_spec(tool: dict[str, Any]) -> dict[str, Any]:
    """Map a Composio tool record to the agent's tool-spec shape."""
    params = tool.get("input_parameters") or {"type": "object", "properties": {}}
    toolkit = tool.get("toolkit") or {}
    return {
        "name": tool["slug"],
        "tool": toolkit.get("slug", "composio"),
        "action": tool["slug"],
        "description": (tool.get("description") or tool.get("name") or "")[:300],
        "parameters": params,
        "provider": "composio",
        "no_auth": bool(tool.get("no_auth")),
    }


def get_default_composio_client() -> ComposioClient:
    return ComposioClient()
