"""Orgs endpoints — client tenant provisioning."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.repositories import provision_org, reset_org_content, try_db
from db.session import get_db, require_admin

router = APIRouter(prefix="/orgs", tags=["orgs"])
DbSession = Annotated[Session, Depends(get_db)]


class OrgCreate(BaseModel):
    name: str
    admin_email: str
    admin_display_name: str


class OrgResponse(BaseModel):
    org_id: str
    name: str
    admin_email: str
    admin_display_name: str


@router.post("", response_model=OrgResponse)
async def create_org(body: OrgCreate, db: DbSession) -> OrgResponse:
    """Provision a new organization (tenant) and its initial admin user."""
    try:

        def _provision():
            return provision_org(
                db,
                name=body.name,
                admin_email=body.admin_email,
                admin_name=body.admin_display_name,
            )

        org, user = try_db("provision_org", (None, None), _provision)
        if not org or not user:
            raise HTTPException(
                status_code=500,
                detail="Database error provisioning organization",
            )

        return OrgResponse(
            org_id=org.id,
            name=org.name,
            admin_email=user.email,
            admin_display_name=user.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{org_id}/reset-content")
async def reset_content(
    org_id: str, db: DbSession, admin: Annotated[dict, Depends(require_admin)]
) -> dict[str, object]:
    """Delete all ingested/derived content for an org (documents, chunks, sync
    runs, workflows, memory) while keeping the org, users, and connector
    connections. Clears seed/demo data so a fresh re-sync pulls only real data."""
    # An admin may only reset their own org.
    if admin.get("org_id") != org_id:
        raise HTTPException(status_code=403, detail="Cannot reset another organization.")
    counts = reset_org_content(db, org_id)
    # Best-effort: also clear this org's vectors from Qdrant.
    try:
        from memory.qdrant_store import get_default_qdrant_store

        await get_default_qdrant_store().delete_org(org_id)
    except Exception:  # noqa: BLE001 — vector cleanup is best-effort
        pass
    return {"org_id": org_id, "deleted": counts}
