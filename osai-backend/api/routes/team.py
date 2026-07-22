"""Team endpoints — members, departments, and invites for an org."""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from db.repositories import (
    create_department,
    create_invite,
    delete_department,
    delete_member,
    get_member_removal_impact,
    list_departments,
    list_invites,
    list_members,
    revoke_invite,
    update_department,
    update_member,
)
from db.session import get_db, get_org_id, require_admin, require_writable_org

router = APIRouter(prefix="/team", tags=["team"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
WriteOrgId = Annotated[str, Depends(require_writable_org)]
AdminClaims = Annotated[dict, Depends(require_admin)]


class DepartmentCreate(BaseModel):
    name: str
    color: str | None = None


class DepartmentUpdate(BaseModel):
    name: str


class InviteCreate(BaseModel):
    email: str
    role: Literal["admin", "member"] = "member"
    department_id: str | None = None
    data_tier: str = "normal"


class MemberUpdate(BaseModel):
    role: Literal["admin", "member"] | None = None
    department_id: str | None = None
    data_tier: str | None = None


def _invite_link(token: str) -> str:
    base = settings.frontend_redirect.rstrip("/")
    # Fragments are never sent in HTTP requests, so the opaque capability does
    # not enter frontend access logs when the recipient opens the link.
    return f"{base}/login#invite={quote(token, safe='')}"


@router.get("/members")
async def get_members(db: DbSession, org_id: OrgId) -> list[dict[str, object]]:
    depts = {d.id: d.name for d in list_departments(db, org_id)}
    return [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "role": u.role,
            "department_id": u.department_id,
            "department": depts.get(u.department_id) if u.department_id else None,
            "data_tier": u.data_tier,
            "status": "active",
        }
        for u in list_members(db, org_id)
    ]


@router.get("/departments")
async def get_departments(db: DbSession, org_id: OrgId) -> list[dict[str, object]]:
    members = list_members(db, org_id)
    counts: dict[str, int] = {}
    for u in members:
        if u.department_id:
            counts[u.department_id] = counts.get(u.department_id, 0) + 1
    return [
        {"id": d.id, "name": d.name, "color": d.color, "members": counts.get(d.id, 0)}
        for d in list_departments(db, org_id)
    ]


@router.post("/departments")
async def add_department(
    body: DepartmentCreate, db: DbSession, org_id: WriteOrgId, _admin: AdminClaims
) -> dict[str, object]:
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Department name is required")
    d = create_department(db, org_id, body.name, body.color)
    return {"id": d.id, "name": d.name, "color": d.color, "members": 0}


@router.patch("/departments/{department_id}")
async def patch_department(
    department_id: str,
    body: DepartmentUpdate,
    db: DbSession,
    org_id: WriteOrgId,
    _admin: AdminClaims,
) -> dict[str, object]:
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Department name is required")
    department = update_department(db, org_id, department_id, body.name)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    return {
        "id": department.id,
        "name": department.name,
        "color": department.color,
    }


@router.delete("/departments/{department_id}")
async def remove_department(
    department_id: str, db: DbSession, org_id: WriteOrgId, _admin: AdminClaims
) -> dict[str, bool]:
    if not delete_department(db, org_id, department_id):
        raise HTTPException(status_code=404, detail="Department not found")
    return {"deleted": True}


@router.get("/invites")
async def get_invites(
    db: DbSession, org_id: OrgId, _admin: AdminClaims
) -> list[dict[str, object]]:
    return [
        {
            "id": i.id,
            "email": i.email,
            "role": i.role,
            "department_id": i.department_id,
            "data_tier": i.data_tier,
            "status": i.status,
            "invite_link": _invite_link(i.token),
        }
        for i in list_invites(db, org_id)
    ]


@router.post("/invites")
async def add_invite(
    body: InviteCreate, db: DbSession, org_id: WriteOrgId, _admin: AdminClaims
) -> dict[str, object]:
    if not body.email.strip():
        raise HTTPException(status_code=400, detail="Email is required")
    invite = create_invite(
        db, org_id, body.email, body.role, body.department_id, body.data_tier
    )
    return {
        "id": invite.id,
        "email": invite.email,
        "role": invite.role,
        "department_id": invite.department_id,
        "data_tier": invite.data_tier,
        "status": invite.status,
        "invite_link": _invite_link(invite.token),
    }


@router.delete("/invites/{invite_id}")
async def remove_invite(
    invite_id: str, db: DbSession, org_id: WriteOrgId, _admin: AdminClaims
) -> dict[str, bool]:
    if not revoke_invite(db, org_id, invite_id):
        raise HTTPException(status_code=404, detail="Pending invite not found")
    return {"revoked": True}


@router.patch("/members/{user_id}")
async def patch_member(
    user_id: str,
    body: MemberUpdate,
    db: DbSession,
    org_id: WriteOrgId,
    _admin: AdminClaims,
) -> dict[str, object]:
    patch: dict[str, object] = {
        "role": body.role,
        "data_tier": body.data_tier,
    }
    if "department_id" in body.model_fields_set:
        patch["department_id"] = body.department_id
    user = update_member(db, user_id, org_id, **patch)
    if user is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return {
        "id": user.id,
        "role": user.role,
        "department_id": user.department_id,
        "data_tier": user.data_tier,
    }


@router.get("/members/{user_id}/removal-impact")
async def member_removal_impact(
    user_id: str, db: DbSession, org_id: OrgId, _admin: AdminClaims
) -> dict[str, object]:
    impact = get_member_removal_impact(db, user_id, org_id)
    if impact is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return impact


@router.delete("/members/{user_id}")
async def remove_member(
    user_id: str,
    db: DbSession,
    org_id: WriteOrgId,
    _admin: AdminClaims,
    transfer_to_user_id: str | None = None,
) -> dict[str, bool]:
    if not delete_member(
        db,
        user_id,
        org_id,
        actor=_admin.get("sub"),
        transfer_to_user_id=transfer_to_user_id,
    ):
        raise HTTPException(status_code=404, detail="Member not found")
    return {"deleted": True}
