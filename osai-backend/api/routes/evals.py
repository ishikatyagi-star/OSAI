"""Eval endpoint — powers the web eval dashboard (P6)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from api.schemas.eval import EvalRun
from db.session import get_org_id
from evals.runner import run_evals

router = APIRouter(prefix="/evals", tags=["evals"])
OrgId = Annotated[str, Depends(get_org_id)]


@router.get("", response_model=EvalRun)
async def get_eval_run(org_id: OrgId) -> EvalRun:
    """Run the fixture suite against the live pipeline and return scored results."""
    return await run_evals(org_id)
