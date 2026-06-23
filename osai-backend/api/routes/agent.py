"""Ask OSAI agent endpoints — POST /ask and action confirmation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from agent.orchestrator import confirm_action, run_ask
from api.schemas.agent import (
    AskRequest,
    AskResponse,
    ConfirmActionRequest,
    ConfirmActionResult,
)
from db.session import get_org_id

router = APIRouter(tags=["agent"])
OrgId = Annotated[str, Depends(get_org_id)]


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest, org_id: OrgId) -> AskResponse:
    """Answer a question over org knowledge (RAG) and propose connector actions."""
    # Trust the authenticated org from the JWT, never the client-supplied body,
    # so a user can't query another org by passing its id.
    request.org_id = org_id
    return await run_ask(request)


@router.post("/ask/actions/{action_id}/confirm", response_model=ConfirmActionResult)
async def confirm(action_id: str, body: ConfirmActionRequest) -> ConfirmActionResult:
    """Execute a previously proposed agent action against its connector."""
    return await confirm_action(action_id, body.conversation_id)
