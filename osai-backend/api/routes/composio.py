"""Composio integration endpoints — list toolkits/tools and connect OAuth apps."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from config import settings
from connectors.composio_ingest import ingest_composio_toolkit, supports_sync, sync_all_connections
from connectors.composio_tool import get_default_composio_client
from db.session import get_db, get_org_id
from workers.tasks.ingest import sync_composio_connections

router = APIRouter(prefix="/integrations/composio", tags=["composio"])
OrgId = Annotated[str, Depends(get_org_id)]
DbSession = Annotated[Session, Depends(get_db)]


def _client_or_404():
    client = get_default_composio_client()
    if not client.available():
        raise HTTPException(status_code=404, detail="Composio is not configured")
    return client


@router.get("/toolkits")
async def list_toolkits(
    org_id: OrgId,
    search: str | None = None,
    category: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=40, ge=1, le=100),
) -> dict:
    """Available Composio apps (Gmail, Calendar, Slack, …)."""
    client = _client_or_404()
    try:
        page = await client.list_toolkits(search=search, category=category, cursor=cursor, limit=limit)
        connections = await client.list_connections(org_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    connected = {(connection.get("toolkit") or "").lower() for connection in connections if (connection.get("status") or "").upper() == "ACTIVE"}
    for item in page["items"]:
        slug = str(item.get("slug") or "").lower()
        item["connected"] = slug in connected
        item["capabilities"] = {"sync": supports_sync(slug), "actions": True}
    return page


@router.get("/toolkit-categories")
async def list_toolkit_categories() -> dict:
    return {"items": await _client_or_404().list_toolkit_categories()}


@router.get("/tools")
async def list_tools(toolkit: str | None = None) -> list[dict]:
    """Tools exposed by the configured (or a given) toolkit, in agent-spec form."""
    client = _client_or_404()
    toolkits = [toolkit] if toolkit else None
    return await client.list_tools(toolkits)


@router.post("/connect/{toolkit}")
async def connect(toolkit: str, org_id: OrgId) -> dict:
    """Begin an OAuth connection for a toolkit. Returns a redirect_url for the user.

    Passes a callback so that, after the user authorizes, OSAI auto-ingests the
    app's data with no further action (see GET /callback)."""
    callback_url = None
    if settings.public_base_url:
        callback_url = (
            f"{settings.public_base_url.rstrip('/')}"
            f"/integrations/composio/callback?org_id={org_id}"
        )
    result = await _client_or_404().connect(toolkit, org_id, callback_url=callback_url)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/callback")
async def callback(org_id: str) -> RedirectResponse:
    """Where Composio sends the user after authorizing. Kicks off ingestion of
    the org's connections in the background, then redirects back immediately."""
    client = get_default_composio_client()
    if client.available():
        sync_composio_connections.delay(org_id)
    # Land the user back on the Integrations page (not the marketing root) so they
    # immediately see the connection they just authorized.
    base = settings.frontend_redirect.rstrip("/")
    return RedirectResponse(url=f"{base}/integrations?connected=1")


@router.post("/sync")
async def sync(org_id: OrgId, db: DbSession) -> dict:
    """Auto-detect all connected apps for the org and ingest them (idempotent)."""
    return await sync_all_connections(org_id, db)


@router.get("/connections")
async def list_connections(org_id: OrgId) -> list[dict]:
    """Connected accounts for this org."""
    return await _client_or_404().list_connections(org_id)


@router.post("/disconnect/{toolkit}")
async def disconnect(toolkit: str, org_id: OrgId) -> dict:
    """Revoke the org's connected account(s) for a toolkit at Composio, so a
    subsequent Connect goes through a fresh OAuth handshake."""
    return await _client_or_404().disconnect(toolkit, org_id)


@router.post("/{toolkit}/ingest")
async def ingest(toolkit: str, org_id: OrgId, db: DbSession) -> dict:
    """Pull documents from a Composio-connected app into OSAI's searchable brain.

    Requires the toolkit to be connected first (POST /connect/{toolkit}). Notion
    is supported today; other toolkits return a clear 'not implemented'.
    """
    _client_or_404()
    result = await ingest_composio_toolkit(org_id, toolkit, db)
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result
