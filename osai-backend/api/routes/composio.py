"""Composio integration endpoints — list toolkits/tools and connect OAuth apps."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from connectors.composio_tool import get_default_composio_client
from db.session import get_org_id

router = APIRouter(prefix="/integrations/composio", tags=["composio"])
OrgId = Annotated[str, Depends(get_org_id)]


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
    """Begin an OAuth connection for a toolkit. Returns a redirect_url for the user."""
    result = await _client_or_404().connect(toolkit, org_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/connections")
async def list_connections(org_id: OrgId) -> list[dict]:
    """Connected accounts for this org."""
    return await _client_or_404().list_connections(org_id)
