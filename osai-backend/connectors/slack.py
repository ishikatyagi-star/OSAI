"""Slack connector v1 — syncs channel messages via Slack Web API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from api.schemas.connector import (
    ActionResult,
    AuthStatus,
    ConnectorAction,
    HealthcheckResult,
    PermissionSet,
    SourceDocument,
    SyncResult,
)
from config import settings
from connectors.base import Connector

SLACK_API = "https://slack.com/api"
MAX_CHANNELS = 50  # channels fetched per sync
MAX_MESSAGES = 200  # messages per channel


class SlackConnector(Connector):
    key = "slack"
    display_name = "Slack"
    capabilities = {"sync", "search", "execute"}

    def __init__(self, token: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.token = token if token is not None else settings.slack_bot_token
        self._client = client

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def auth_status(self, org_id: str) -> AuthStatus:
        if not self.token:
            return AuthStatus(
                connector_key=self.key,
                connected=False,
                error="Set OSAI_SLACK_BOT_TOKEN to enable Slack sync.",
            )
        try:
            data = await self._call("auth.test")
            if not data.get("ok"):
                return AuthStatus(
                    connector_key=self.key,
                    connected=False,
                    error=data.get("error", "auth.test failed"),
                )
            return AuthStatus(
                connector_key=self.key,
                connected=True,
                scopes=["channels:history", "channels:read"],
            )
        except httpx.HTTPError as exc:
            return AuthStatus(connector_key=self.key, connected=False, error=str(exc))

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    async def sync(self, org_id: str, cursor: str | None = None) -> SyncResult:
        auth = await self.auth_status(org_id)
        if not auth.connected:
            import sys
            if "pytest" in sys.modules:
                return SyncResult(connector_key=self.key, status="failed", error=auth.error)

            # Real connections come through Composio OAuth; the native connector
            # only syncs with its own credentials and must never emit demo data
            # into a customer workspace.
            return SyncResult(
                connector_key=self.key,
                status="failed",
                error=auth.error or "Not connected. Use Connect to authorize this source.",
            )

            # Dev demo fallback data (unreachable; kept for local reference)
            documents = [
                SourceDocument(
                    source_id="doc-slack-onboarding",
                    source_type=self.key,
                    org_id=org_id,
                    external_id="slack-channel-onboarding",
                    title="OSAI Team Onboarding Guidelines",
                    text=(
                        "Welcome to the OSAI team! Read the onboarding guide in Notion "
                        "and hook up your Linear accounts. The developer environment "
                        "runs in Docker over the internal bridge network. Ensure your "
                        "local .env is populated. The API is on port 8000 and Qdrant is "
                        "on port 6333."
                    ),
                    metadata={"title": "OSAI Team Onboarding Guidelines"},
                    permissions=["source:all"],
                    data_tier="normal",
                    created_at=datetime.now(),
                )
            ]
            return SyncResult(connector_key=self.key, status="succeeded", documents=documents)

        try:
            channels = await self._list_channels(cursor)
            documents: list[SourceDocument] = []
            for channel in channels[:MAX_CHANNELS]:
                msgs = await self._fetch_messages(channel["id"])
                if msgs:
                    doc = self._messages_to_document(org_id, channel, msgs)
                    documents.append(doc)
            return SyncResult(connector_key=self.key, status="succeeded", documents=documents)
        except httpx.HTTPError as exc:
            return SyncResult(connector_key=self.key, status="failed", error=str(exc))

    # ------------------------------------------------------------------
    # Permissions / search / execute / healthcheck
    # ------------------------------------------------------------------

    async def get_permissions(self, document: SourceDocument) -> PermissionSet:
        return PermissionSet(principals=document.permissions, public=False)

    async def search(self, org_id: str, query: str) -> list[SourceDocument]:
        result = await self.sync(org_id)
        q = query.lower()
        return [d for d in result.documents if q in d.title.lower() or q in d.text.lower()]

    async def execute_action(self, org_id: str, action: ConnectorAction) -> ActionResult:
        """Post a message to a Slack channel (action_type='post_message')."""
        if not self.token:
            return ActionResult(
                connector_key=self.key, status="skipped", error="Slack token not configured."
            )
        if action.action_type != "post_message":
            return ActionResult(
                connector_key=self.key,
                status="skipped",
                error=f"Unsupported action_type: {action.action_type}",
            )
        channel = action.payload.get("channel", "general")
        text = action.payload.get("text", "")
        try:
            data = await self._call("chat.postMessage", json={"channel": channel, "text": text})
            if not data.get("ok"):
                return ActionResult(
                    connector_key=self.key,
                    status="failed",
                    error=data.get("error", "chat.postMessage failed"),
                )
            return ActionResult(
                connector_key=self.key,
                status="succeeded",
                external_id=data.get("ts"),
                url=f"https://slack.com/archives/{channel}/p{data.get('ts', '').replace('.', '')}",
            )
        except httpx.HTTPError as exc:
            return ActionResult(connector_key=self.key, status="failed", error=str(exc))

    async def healthcheck(self, org_id: str) -> HealthcheckResult:
        auth = await self.auth_status(org_id)
        return HealthcheckResult(
            connector_key=self.key,
            healthy=auth.connected,
            message=auth.error or "Slack bot token configured",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _list_channels(self, cursor: str | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"types": "public_channel", "limit": MAX_CHANNELS}
        if cursor:
            params["cursor"] = cursor
        data = await self._call("conversations.list", params=params)
        return data.get("channels", [])

    async def _fetch_messages(self, channel_id: str) -> list[dict[str, Any]]:
        data = await self._call(
            "conversations.history",
            params={"channel": channel_id, "limit": MAX_MESSAGES},
        )
        return [m for m in data.get("messages", []) if m.get("type") == "message" and m.get("text")]

    def _messages_to_document(
        self, org_id: str, channel: dict[str, Any], messages: list[dict[str, Any]]
    ) -> SourceDocument:
        channel_id = channel["id"]
        channel_name = channel.get("name", channel_id)
        text = "\n".join(f"[{_ts_to_iso(m.get('ts', ''))}] {m['text']}" for m in messages)
        latest_ts = max((m.get("ts", "0") for m in messages), default="0")
        return SourceDocument(
            source_id=f"{org_id}:slack:channel:{channel_id}",
            source_type="slack",
            org_id=org_id,
            external_id=channel_id,
            title=f"#{channel_name}",
            url=f"https://slack.com/archives/{channel_id}",
            text=text or f"#{channel_name}",
            metadata={"channel_name": channel_name, "message_count": len(messages)},
            permissions=[f"slack:channel:{channel_id}"],
            data_tier="normal",
            updated_at=_ts_to_datetime(latest_ts),
        )

    async def _call(
        self,
        api_method: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}"}
        url = f"{SLACK_API}/{api_method}"
        http_method = "POST" if json is not None else "GET"
        if self._client:
            r = await self._client.request(
                http_method, url, headers=headers, params=params, json=json
            )
            r.raise_for_status()
            return r.json()
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.request(http_method, url, headers=headers, params=params, json=json)
            r.raise_for_status()
            return r.json()


def _ts_to_iso(ts: str) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()
    except (ValueError, OSError):
        return ts


def _ts_to_datetime(ts: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (ValueError, OSError):
        return None
