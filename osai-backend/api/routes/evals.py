"""Eval endpoint — powers the web eval dashboard (P6)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.ratelimit import EVAL_RUN_BUDGET, rate_limit
from api.schemas.eval import EvalRun
from db.session import get_org_id, require_admin
from evals.runner import run_evals

router = APIRouter(prefix="/evals", tags=["evals"])
OrgId = Annotated[str, Depends(get_org_id)]
AdminOnly = Annotated[dict, Depends(require_admin)]


@router.get("")
async def get_eval_run(_org_id: OrgId, _admin: AdminOnly) -> None:
    """A read request must never trigger the costly live evaluation pipeline."""
    raise HTTPException(
        status_code=405,
        detail="Use POST to run evaluations.",
        headers={"Allow": "POST"},
    )


@router.post(
    "",
    response_model=EvalRun,
    dependencies=[Depends(rate_limit(*EVAL_RUN_BUDGET))],
)
async def create_eval_run(admin: AdminOnly) -> EvalRun:
    """Run the fixture suite as the current org admin and return scored results."""
    user_id = admin.get("sub")
    permissions = ["role:admin"]
    if user_id:
        permissions.append(f"user:{user_id}")
    return await run_evals(
        admin["org_id"],
        requester_permissions=permissions,
        requester_tier="red",
        requester_user_id=user_id,
    )
