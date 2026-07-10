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
import time
from typing import Any

import httpx

from config import settings

logger = logging.getLogger("osai.composio")

# Minimal OAuth scopes to request per toolkit. OSAI only reads/indexes content,
# so we ask for read-only access rather than the broad default (e.g. full Drive)
# to keep the consent screen honest and reduce the trust ask.
TOOLKIT_SCOPES: dict[str, list[str]] = {
    "googledrive": ["https://www.googleapis.com/auth/drive.readonly"],
}


class ComposioClient:
    _catalog_cache: dict[tuple[str, str, str, int], tuple[float, dict[str, Any]]] = {}
    _catalog_ttl_seconds = 600

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or settings.composio_api_key
        self.base_url = (base_url or settings.composio_base_url).rstrip("/")

    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key or "", "Content-Type": "application/json"}

    async def list_tools(
        self, toolkits: list[str] | None = None, limit: int = 20, *, important: bool = False
    ) -> list[dict[str, Any]]:
        """Return Composio tools mapped into OSAI agent tool-spec format."""
        toolkits = toolkits or settings.composio_toolkit_list
        specs: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30) as client:
            for toolkit in toolkits:
                resp = await client.get(
                    f"{self.base_url}/api/v3/tools",
                    headers=self._headers(),
                    params={"toolkit_slug": toolkit, "limit": limit, "important": str(important).lower()},
                )
                if resp.status_code != 200:
                    logger.warning("Composio list_tools %s -> %s", toolkit, resp.status_code)
                    continue
                for tool in resp.json().get("items", []):
                    specs.append(_to_spec(tool))
        return specs

    async def list_toolkits(self, *, search: str | None = None, category: str | None = None, cursor: str | None = None, limit: int = 40) -> dict[str, Any]:
        """Return a cursor-paginated Composio catalog page."""
        key = (search or "", category or "", cursor or "", min(max(limit, 1), 100))
        now = time.monotonic()
        cached = self._catalog_cache.get(key)
        if cached and now - cached[0] < self._catalog_ttl_seconds:
            return cached[1]
        params = {"limit": key[3], "sort_by": "usage"}
        if search:
            params["search"] = search
        if category:
            params["category"] = category
        if cursor:
            params["cursor"] = cursor
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/api/v3.1/toolkits",
                headers=self._headers(),
                params=params,
            )
        if resp.status_code != 200:
            if cached:
                return cached[1]
            raise RuntimeError(f"Composio toolkit catalog returned HTTP {resp.status_code}")
        out: list[dict[str, Any]] = []
        for tk in resp.json().get("items", []):
            meta = tk.get("meta", {})
            out.append(
                {
                    "slug": tk.get("slug"),
                    "name": tk.get("name"),
                    "auth_schemes": tk.get("auth_schemes", []),
                    "no_auth": not tk.get("auth_schemes"),
                    "tools_count": meta.get("tools_count"),
                    "logo": meta.get("logo"),
                    "categories": [c.get("name") for c in meta.get("categories", [])],
                }
            )
        result = {"items": out, "next_cursor": resp.json().get("next_cursor")}
        self._catalog_cache[key] = (now, result)
        return result

    async def list_toolkit_categories(self) -> list[dict[str, Any]]:
        key = ("categories", "", "", 0)
        now = time.monotonic()
        cached = self._catalog_cache.get(key)
        if cached and now - cached[0] < self._catalog_ttl_seconds:
            return cached[1]["items"]
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.base_url}/api/v3.1/toolkits/categories", headers=self._headers())
        if resp.status_code != 200:
            return cached[1]["items"] if cached else []
        items = [{"id": item.get("id"), "name": item.get("name")} for item in resp.json().get("items", [])]
        self._catalog_cache[key] = (now, {"items": items})
        return items

    async def _ensure_auth_config(self, client: httpx.AsyncClient, toolkit: str) -> str | None:
        """Return an auth_config id for a toolkit, creating a managed one if needed.

        For toolkits in TOOLKIT_SCOPES we request only the minimal OAuth scopes
        (e.g. Google Drive read-only) so the consent screen matches what OSAI
        actually does — index and search, not modify.
        """
        resp = await client.get(
            f"{self.base_url}/api/v3/auth_configs",
            headers=self._headers(),
            params={"toolkit_slug": toolkit, "limit": 1},
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                return items[0].get("id")

        managed: dict[str, Any] = {"type": "use_composio_managed_auth"}
        scopes = TOOLKIT_SCOPES.get(toolkit)
        if scopes:
            managed["scopes"] = scopes
        payload = {"toolkit": {"slug": toolkit}, "auth_config": managed}

        created = await client.post(
            f"{self.base_url}/api/v3/auth_configs", headers=self._headers(), json=payload
        )
        # If the provider rejects the scoped payload, retry without scopes so a
        # connection can still be established (broad scope) rather than failing.
        if created.status_code not in (200, 201) and scopes:
            payload["auth_config"] = {"type": "use_composio_managed_auth"}
            created = await client.post(
                f"{self.base_url}/api/v3/auth_configs", headers=self._headers(), json=payload
            )
        if created.status_code in (200, 201):
            body = created.json()
            return body.get("auth_config", body).get("id")
        logger.warning("Composio auth_config create %s -> %s", toolkit, created.status_code)
        return None

    async def connect(
        self, toolkit: str, user_id: str, callback_url: str | None = None
    ) -> dict[str, Any]:
        """Start an OAuth connection. Returns {redirect_url, connected_account_id}.
        callback_url is where Composio sends the user after authorizing."""
        async with httpx.AsyncClient(timeout=30) as client:
            auth_config_id = await self._ensure_auth_config(client, toolkit)
            if not auth_config_id:
                return {"error": f"Could not get auth config for {toolkit}"}
            payload = {"auth_config_id": auth_config_id, "user_id": user_id}
            if callback_url:
                payload["callback_url"] = callback_url
            resp = await client.post(
                f"{self.base_url}/api/v3/connected_accounts/link",
                headers=self._headers(),
                json=payload,
            )
        if resp.status_code not in (200, 201):
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        body = resp.json()
        return {
            "redirect_url": body.get("redirect_url"),
            "connected_account_id": body.get("connected_account_id"),
            "expires_at": body.get("expires_at"),
        }

    async def list_connections(self, user_id: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/api/v3/connected_accounts",
                headers=self._headers(),
                params={"user_ids": user_id, "limit": 50},
            )
        if resp.status_code != 200:
            return []
        return [
            {
                "id": c.get("id"),
                "toolkit": (c.get("toolkit") or {}).get("slug"),
                "status": c.get("status"),
                "email": _extract_account_email(c),
            }
            for c in resp.json().get("items", [])
        ]

    async def connection_identity(self, toolkit: str, user_id: str) -> dict[str, Any] | None:
        """Return {id, email} for the org's active connected account for a toolkit,
        or None if there's no active connection. Identifies which external account
        (e.g. which Google user) is currently connected, for reconnect handling."""
        target = toolkit.lower()
        for c in await self.list_connections(user_id):
            if (c.get("toolkit") or "").lower() != target:
                continue
            if (c.get("status") or "").upper() not in ("ACTIVE", "INITIATED", ""):
                continue
            return {"id": c.get("id"), "email": c.get("email")}
        return None

    async def disconnect(self, toolkit: str, user_id: str) -> dict[str, Any]:
        """Revoke this org's connected account(s) for a toolkit at Composio, so a
        later Connect starts a fresh OAuth handshake. Returns {deleted: N}."""
        connections = await self.list_connections(user_id)
        target = toolkit.lower()
        ids = [
            c["id"]
            for c in connections
            if c.get("id") and (c.get("toolkit") or "").lower() == target
        ]
        deleted = 0
        async with httpx.AsyncClient(timeout=30) as client:
            for cid in ids:
                resp = await client.delete(
                    f"{self.base_url}/api/v3/connected_accounts/{cid}",
                    headers=self._headers(),
                )
                if resp.status_code in (200, 204):
                    deleted += 1
        return {"deleted": deleted}

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


def _extract_account_email(account: dict[str, Any]) -> str | None:
    """Best-effort pull of the connected account's email from a Composio
    connected_account record. Composio nests provider identity differently across
    toolkits, so probe the common locations rather than assume one shape."""
    candidates: list[Any] = [
        account.get("email"),
        (account.get("data") or {}).get("email"),
        ((account.get("connection_params") or {}).get("val") or {}).get("email"),
        ((account.get("params") or {}).get("val") or {}).get("email"),
        (account.get("meta") or {}).get("email"),
    ]
    for c in candidates:
        if isinstance(c, str) and "@" in c:
            return c
    return None


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
