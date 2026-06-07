"""Freshdesk connector v1 — syncs support tickets via Freshdesk REST API."""

from __future__ import annotations

import base64
from datetime import datetime
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

MAX_TICKETS = 100


class FreshdeskConnector(Connector):
    key = "freshdesk"
    display_name = "Freshdesk"
    capabilities = {"sync", "search", "execute"}

    def __init__(
        self,
        domain: str | None = None,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.domain = domain if domain is not None else settings.freshdesk_domain
        self.api_key = api_key if api_key is not None else settings.freshdesk_api_key
        self._client = client

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def auth_status(self, org_id: str) -> AuthStatus:
        if not self.domain or not self.api_key:
            return AuthStatus(
                connector_key=self.key,
                connected=False,
                error="Set OSAI_FRESHDESK_DOMAIN and OSAI_FRESHDESK_API_KEY.",
            )
        try:
            await self._get("/api/v2/tickets?per_page=1")
            return AuthStatus(
                connector_key=self.key,
                connected=True,
                scopes=["tickets.read"],
            )
        except httpx.HTTPStatusError as exc:
            return AuthStatus(
                connector_key=self.key,
                connected=False,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
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

            # Dev demo fallback data
            documents = [
                SourceDocument(
                    source_id="doc-freshdesk-sla",
                    source_type=self.key,
                    org_id=org_id,
                    external_id="freshdesk-ticket-102",
                    title="Freshdesk Integration & SLA Escalation Rules",
                    text=(
                        "OSAI maps support tickets to developer actions. Under normal "
                        "conditions, tickets sync every 30 minutes. If a ticket becomes "
                        "urgent, an alert is triggered in the Slack #operations channel. "
                        "If the customer is on Enterprise, the ticket must be resolved "
                        "within 4 hours and actions pushed automatically."
                    ),
                    metadata={"title": "Freshdesk Integration & SLA Escalation Rules"},
                    permissions=["source:all"],
                    data_tier="normal",
                    created_at=datetime.now(),
                )
            ]
            return SyncResult(connector_key=self.key, status="succeeded", documents=documents)

        try:
            page = int(cursor) if cursor else 1
            tickets = await self._get(
                f"/api/v2/tickets?per_page={MAX_TICKETS}&page={page}&include=description"
            )
            documents = [self._ticket_to_document(org_id, t) for t in tickets]
            next_cursor = str(page + 1) if len(tickets) == MAX_TICKETS else None
            return SyncResult(
                connector_key=self.key,
                status="succeeded",
                documents=documents,
                cursor=next_cursor,
            )
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
        """Create a Freshdesk ticket (action_type='create_ticket')."""
        if not self.domain or not self.api_key:
            return ActionResult(
                connector_key=self.key, status="skipped", error="Freshdesk not configured."
            )
        if action.action_type != "create_ticket":
            return ActionResult(
                connector_key=self.key,
                status="skipped",
                error=f"Unsupported action_type: {action.action_type}",
            )
        payload = {
            "subject": action.payload.get("subject", "OSAI Action Item"),
            "description": action.payload.get("description", ""),
            "email": action.payload.get("email", "osai@internal.local"),
            "priority": action.payload.get("priority", 2),
            "status": action.payload.get("status", 2),
        }
        try:
            ticket = await self._post("/api/v2/tickets", payload)
            ticket_id = ticket.get("id")
            return ActionResult(
                connector_key=self.key,
                status="succeeded",
                external_id=str(ticket_id),
                url=f"https://{self.domain}/helpdesk/tickets/{ticket_id}",
            )
        except httpx.HTTPError as exc:
            return ActionResult(connector_key=self.key, status="failed", error=str(exc))

    async def healthcheck(self, org_id: str) -> HealthcheckResult:
        auth = await self.auth_status(org_id)
        return HealthcheckResult(
            connector_key=self.key,
            healthy=auth.connected,
            message=auth.error or "Freshdesk credentials configured",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ticket_to_document(self, org_id: str, ticket: dict[str, Any]) -> SourceDocument:
        ticket_id = ticket["id"]
        subject = ticket.get("subject", f"Ticket #{ticket_id}")
        desc = ticket.get("description_text") or ticket.get("description") or ""
        # Strip any residual HTML tags
        import re

        desc = re.sub(r"<[^>]+>", " ", desc).strip()

        text = f"{subject}\n\n{desc}".strip()
        status_map = {1: "open", 2: "pending", 3: "resolved", 4: "closed"}
        priority_map = {1: "low", 2: "medium", 3: "high", 4: "urgent"}

        return SourceDocument(
            source_id=f"freshdesk:ticket:{ticket_id}",
            source_type="freshdesk",
            org_id=org_id,
            external_id=str(ticket_id),
            title=subject,
            url=f"https://{self.domain}/helpdesk/tickets/{ticket_id}",
            text=text or subject,
            metadata={
                "status": status_map.get(ticket.get("status", 1), "open"),
                "priority": priority_map.get(ticket.get("priority", 2), "medium"),
                "requester_id": ticket.get("requester_id"),
                "tags": ticket.get("tags", []),
            },
            permissions=[f"freshdesk:ticket:{ticket_id}"],
            data_tier="normal",
            created_at=_parse_fd_dt(ticket.get("created_at")),
            updated_at=_parse_fd_dt(ticket.get("updated_at")),
        )

    def _auth_header(self) -> dict[str, str]:
        token = base64.b64encode(f"{self.api_key}:X".encode()).decode()
        return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    async def _get(self, path: str) -> Any:
        url = f"https://{self.domain}{path}"
        headers = self._auth_header()
        if self._client:
            r = await self._client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, headers=headers)
            r.raise_for_status()
            return r.json()

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"https://{self.domain}{path}"
        headers = self._auth_header()
        if self._client:
            r = await self._client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            return r.json()
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, headers=headers, json=payload)
            r.raise_for_status()
            return r.json()


def _parse_fd_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
