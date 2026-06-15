"""Composio integration endpoints — list toolkits/tools and connect OAuth apps."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from config import settings
from connectors.composio_ingest import ingest_composio_toolkit, sync_all_connections
from connectors.composio_tool import get_default_composio_client
from db.session import get_db, get_org_id

router = APIRouter(prefix="/integrations/composio", tags=["composio"])
OrgId = Annotated[str, Depends(get_org_id)]
DbSession = Annotated[Session, Depends(get_db)]


def _client_or_404():
    client = get_default_composio_client()
    if not client.available():
        raise HTTPException(status_code=404, detail="Composio is not configured")
    return client


@router.get("/toolkits")
async def list_toolkits() -> list[dict]:
    """Available Composio apps (Gmail, Calendar, Slack, …)."""
    return await _client_or_404().list_toolkits()


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
async def callback(org_id: str, db: DbSession) -> RedirectResponse:
    """Where Composio sends the user after authorizing. Auto-ingests every active
    connection for the org, then redirects back to the frontend."""
    client = get_default_composio_client()
    if client.available():
        try:
            await sync_all_connections(org_id, db)
        except Exception:  # noqa: BLE001 — never break the user's redirect
            pass
    return RedirectResponse(url=settings.frontend_redirect)


@router.post("/sync")
async def sync(org_id: OrgId, db: DbSession) -> dict:
    """Auto-detect all connected apps for the org and ingest them (idempotent)."""
    return await sync_all_connections(org_id, db)


@router.get("/connections")
async def list_connections(org_id: OrgId) -> list[dict]:
    """Connected accounts for this org."""
    return await _client_or_404().list_connections(org_id)


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
