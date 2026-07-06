"""Ask OSAI agent endpoints — POST /ask and action confirmation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agent.orchestrator import confirm_action, run_ask
from api.schemas.agent import (
    AskRequest,
    AskResponse,
    ConfirmActionRequest,
    ConfirmActionResult,
)
from db.repositories import user_permissions
from db.session import get_db, get_optional_claims, get_org_id

router = APIRouter(tags=["agent"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]


@router.post("/ask", response_model=AskResponse)
async def ask(
    request: AskRequest, db: DbSession, org_id: OrgId, claims: OptionalClaims
) -> AskResponse:
    """Answer a question over org knowledge (RAG) and propose connector actions."""
    # Org + permissions come from the verified session, not the request body.
    request.org_id = org_id
    return await run_ask(request, requester_permissions=user_permissions(db, claims))


@router.post("/ask/actions/{action_id}/confirm", response_model=ConfirmActionResult)
async def confirm(
    action_id: str, body: ConfirmActionRequest, org_id: OrgId
) -> ConfirmActionResult:
    """Execute a previously proposed agent action against its connector."""
    return await confirm_action(action_id, body.conversation_id, caller_org_id=org_id)
