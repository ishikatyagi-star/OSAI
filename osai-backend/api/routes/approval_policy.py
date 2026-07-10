from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.approval_policy import approval_policy
from db.models import Org
from db.session import get_db, get_org_id, require_admin

router = APIRouter(prefix="/settings/approval-policy", tags=["settings"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
AdminClaims = Annotated[dict, Depends(require_admin)]


class ApprovalPolicyUpdate(BaseModel):
    approver_role: Literal["admin", "member"] = "admin"
    require_separate_approver: bool = False


@router.get("")
async def get_approval_policy(db: DbSession, org_id: OrgId) -> dict[str, object]:
    org = db.get(Org, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return approval_policy(org.data_routing)


@router.put("")
async def update_approval_policy(
    body: ApprovalPolicyUpdate, db: DbSession, claims: AdminClaims
) -> dict[str, object]:
    org = db.get(Org, claims["org_id"])
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    routing = dict(org.data_routing or {})
    routing["approval_policy"] = body.model_dump()
    org.data_routing = routing
    db.commit()
    return approval_policy(org.data_routing)
