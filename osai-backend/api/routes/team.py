"""Team endpoints — members, departments, and invites for an org."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from db.repositories import (
    create_department,
    create_invite,
    list_departments,
    list_invites,
    list_members,
    update_member,
)
from db.session import get_db, get_org_id

router = APIRouter(prefix="/team", tags=["team"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]


class DepartmentCreate(BaseModel):
    name: str
    color: str | None = None


class InviteCreate(BaseModel):
    email: str
    role: str = "member"
    department_id: str | None = None


class MemberUpdate(BaseModel):
    role: str | None = None
    department_id: str | None = None


def _invite_link(email: str) -> str:
    base = settings.frontend_redirect.rstrip("/")
    return f"{base}/login?invite={quote(email)}"


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
    body: DepartmentCreate, db: DbSession, org_id: OrgId
) -> dict[str, object]:
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Department name is required")
    d = create_department(db, org_id, body.name, body.color)
    return {"id": d.id, "name": d.name, "color": d.color, "members": 0}


@router.get("/invites")
async def get_invites(db: DbSession, org_id: OrgId) -> list[dict[str, object]]:
    return [
        {
            "id": i.id,
            "email": i.email,
            "role": i.role,
            "department_id": i.department_id,
            "status": i.status,
            "invite_link": _invite_link(i.email),
        }
        for i in list_invites(db, org_id)
    ]


@router.post("/invites")
async def add_invite(body: InviteCreate, db: DbSession, org_id: OrgId) -> dict[str, object]:
    if not body.email.strip():
        raise HTTPException(status_code=400, detail="Email is required")
    invite = create_invite(db, org_id, body.email, body.role, body.department_id)
    return {
        "id": invite.id,
        "email": invite.email,
        "role": invite.role,
        "department_id": invite.department_id,
        "status": invite.status,
        "invite_link": _invite_link(invite.email),
    }


@router.patch("/members/{user_id}")
async def patch_member(
    user_id: str, body: MemberUpdate, db: DbSession, org_id: OrgId
) -> dict[str, object]:
    user = update_member(
        db, user_id, org_id, role=body.role, department_id=body.department_id
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return {
        "id": user.id,
        "role": user.role,
        "department_id": user.department_id,
    }
