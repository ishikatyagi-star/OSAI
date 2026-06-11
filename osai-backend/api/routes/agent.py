"""Ask OSAI agent endpoints — POST /ask and action confirmation."""

from __future__ import annotations

from fastapi import APIRouter

from agent.orchestrator import confirm_action, run_ask
from api.schemas.agent import (
    AskRequest,
    AskResponse,
    ConfirmActionRequest,
    ConfirmActionResult,
)

router = APIRouter(tags=["agent"])


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    """Answer a question over org knowledge (RAG) and propose connector actions."""
    return await run_ask(request)


@router.post("/ask/actions/{action_id}/confirm", response_model=ConfirmActionResult)
async def confirm(action_id: str, body: ConfirmActionRequest) -> ConfirmActionResult:
    """Execute a previously proposed agent action against its connector."""
    return await confirm_action(action_id, body.conversation_id)
