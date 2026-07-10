"""Ask OSAI agent endpoints — POST /ask and action confirmation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.orchestrator import confirm_action, run_ask
from api.schemas.agent import (
    AskRequest,
    AskResponse,
    ChatMessage,
    ConfirmActionRequest,
    ConfirmActionResult,
)
from db.approval_policy import approval_policy, may_approve
from db.repositories import user_clearance, user_permissions
from db.models import Conversation, ConversationMessage, ModelCall, Org, User
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
    # Org + permissions + clearance + user come from the verified session.
    request.org_id = org_id
    user_id = claims.get("sub") if claims else None
    if request.conversation_id:
        statement = select(Conversation).where(
            Conversation.id == request.conversation_id,
            Conversation.org_id == org_id,
        )
        if user_id:
            statement = statement.where(Conversation.user_id == user_id)
        conversation = db.scalar(statement)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        rows = db.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(10)
        ).all()
        request.history = [ChatMessage(role=row.role, content=row.content) for row in reversed(rows)]
    response = await run_ask(
        request,
        requester_permissions=user_permissions(db, claims),
        requester_tier=user_clearance(db, claims),
        user_id=user_id,
    )
    route_parts = (response.model_route or "unknown:unknown").split(":", 1)
    db.add(
        ModelCall(
            org_id=org_id,
            provider=route_parts[0],
            model=route_parts[1] if len(route_parts) > 1 else "unknown",
            prompt_version="ask-v1",
            schema_version="ask-response-v1",
            data_tier=user_clearance(db, claims),
            trace_id=response.conversation_id,
        )
    )
    conversation = db.get(Conversation, response.conversation_id)
    if conversation is None:
        conversation = Conversation(id=response.conversation_id, org_id=org_id, user_id=user_id)
        db.add(conversation)
    db.add_all(
        [
            ConversationMessage(conversation_id=response.conversation_id, role="user", content=request.question),
            ConversationMessage(conversation_id=response.conversation_id, role="assistant", content=response.answer),
        ]
    )
    db.commit()
    return response


@router.post("/ask/actions/{action_id}/confirm", response_model=ConfirmActionResult)
async def confirm(
    action_id: str, body: ConfirmActionRequest, db: DbSession, org_id: OrgId, claims: OptionalClaims
) -> ConfirmActionResult:
    """Execute a previously proposed agent action against its connector."""
    user_id = claims.get("sub") if claims else None
    user = db.get(User, user_id) if user_id else None
    org = db.get(Org, org_id)
    policy = approval_policy(org.data_routing if org else None)
    if user is None or user.org_id != org_id or not may_approve(user.role, policy):
        raise HTTPException(status_code=403, detail="Your role cannot approve actions in this workspace.")
    return await confirm_action(
        action_id,
        body.conversation_id,
        caller_org_id=org_id,
        caller_user_id=user_id,
        require_separate_approver=bool(policy["require_separate_approver"]),
    )
