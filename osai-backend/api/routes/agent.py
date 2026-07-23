"""Ask OSAI agent endpoints — POST /ask and action confirmation."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from agent.orchestrator import confirm_action, dismiss_action, run_ask
from api.ratelimit import INTERACTIVE_AI_BUDGET, PROVIDER_ACTION_BUDGET, rate_limit
from api.routes.threads import (
    ask_exchange_lease_expired,
    claim_ask_exchange,
    fail_ask_exchange,
    load_completed_ask_exchange,
    record_ask_exchange,
    refresh_ask_exchange,
    reserve_ask_exchange,
    store_ask_exchange_answer,
    validate_ask_thread,
)
from api.schemas.agent import (
    AskRequest,
    AskResponse,
    ConfirmActionRequest,
    ConfirmActionResult,
    DismissActionResult,
)
from config import settings
from db.repositories import current_org_actor, user_clearance, user_permissions
from db.session import get_db, get_optional_claims, require_writable_org

router = APIRouter(tags=["agent"])
DbSession = Annotated[Session, Depends(get_db)]
# Confirming an action drives a real connector side effect, so the anonymous
# demo workspace must not reach it (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]
_DUPLICATE_WAIT_SECONDS = 20.0


def _ask_persistence_error(
    request_id: object,
    *,
    code: str,
    message: str,
    status_code: int = 503,
    retriable: bool = True,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "retriable": retriable,
            "request_id": str(request_id),
        },
        headers={"Retry-After": "1"} if retriable else None,
    )


async def _wait_for_exchange(db: Session, exchange_id: str):
    deadline = monotonic() + _DUPLICATE_WAIT_SECONDS
    while monotonic() < deadline:
        await asyncio.sleep(0.2)
        row = refresh_ask_exchange(db, exchange_id)
        if row is None or row.status != "running" or ask_exchange_lease_expired(row):
            return row
    return refresh_ask_exchange(db, exchange_id)


@router.post(
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(rate_limit(*INTERACTIVE_AI_BUDGET))],
)
async def ask(
    request: AskRequest, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> AskResponse:
    """Answer a question over org knowledge (RAG) and propose connector actions."""
    # Org + permissions + clearance + user come from the verified session.
    request.org_id = org_id
    user_id = claims.get("sub") if claims else None
    request_id = request.request_id
    persist = bool(
        request_id and user_id and (org_id != settings.default_org_id or settings.env == "local")
    )
    if not persist or request_id is None or user_id is None:
        return await run_ask(
            request,
            requester_permissions=user_permissions(db, claims),
            requester_tier=user_clearance(db, claims),
            user_id=user_id,
        )

    request_payload = request.model_dump(mode="json")
    if request.intent == "ask":
        # Keep the legacy/default Ask hash stable across this deployment while
        # still making action-intent retries conflict with a different intent.
        request_payload.pop("intent", None)
    try:
        exchange, owns_lease = reserve_ask_exchange(
            db,
            org_id=org_id,
            user_id=user_id,
            request_id=request_id,
            request_payload=request_payload,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise _ask_persistence_error(
            request_id,
            code="ask_persistence_failed",
            message="The Ask request could not be reserved safely. Retry it.",
        ) from exc

    while not owns_lease:
        if exchange.status == "completed":
            try:
                completed = load_completed_ask_exchange(
                    db, row=exchange, org_id=org_id, user_id=user_id
                )
            except HTTPException as exc:
                raise _ask_persistence_error(
                    request_id,
                    code="ask_thread_unavailable",
                    message="This thread is no longer available. Refresh your threads.",
                    status_code=409,
                    retriable=False,
                ) from exc
            if completed is not None:
                return completed
            raise _ask_persistence_error(
                request_id,
                code="ask_persistence_failed",
                message="The saved Ask response is unavailable. Retry it.",
            )
        if exchange.status == "answered":
            break
        if exchange.status == "failed" or ask_exchange_lease_expired(exchange):
            try:
                exchange, owns_lease = claim_ask_exchange(db, exchange)
            except (SQLAlchemyError, ValueError) as exc:
                db.rollback()
                raise _ask_persistence_error(
                    request_id,
                    code="ask_persistence_failed",
                    message="The Ask request could not be claimed safely. Retry it.",
                ) from exc
            if owns_lease:
                break
            continue
        if exchange.status != "running":
            raise _ask_persistence_error(
                request_id,
                code="ask_persistence_failed",
                message="The Ask request has an invalid persistence state.",
            )
        try:
            current = await _wait_for_exchange(db, exchange.id)
        except SQLAlchemyError as exc:
            db.rollback()
            raise _ask_persistence_error(
                request_id,
                code="ask_persistence_failed",
                message="The Ask request status could not be checked. Retry it.",
            ) from exc
        if current is None:
            raise _ask_persistence_error(
                request_id,
                code="ask_persistence_failed",
                message="The Ask request reservation disappeared. Retry it.",
            )
        exchange = current
        if exchange.status == "running" and not ask_exchange_lease_expired(exchange):
            raise _ask_persistence_error(
                request_id,
                code="ask_still_processing",
                message="This Ask request is still processing. Retry it shortly.",
            )

    if owns_lease:
        if request.thread_id:
            try:
                validate_ask_thread(db, org_id, user_id, request.thread_id)
            except HTTPException as exc:
                fail_ask_exchange(db, exchange)
                raise _ask_persistence_error(
                    request_id,
                    code="ask_thread_unavailable",
                    message="This thread is no longer available. Refresh your threads.",
                    status_code=409,
                    retriable=False,
                ) from exc
        try:
            response = await run_ask(
                request,
                requester_permissions=user_permissions(db, claims),
                requester_tier=user_clearance(db, claims),
                user_id=user_id,
            )
        except Exception:
            fail_ask_exchange(db, exchange)
            raise
        try:
            exchange = store_ask_exchange_answer(db, exchange, response)
        except (SQLAlchemyError, ValueError) as exc:
            db.rollback()
            raise _ask_persistence_error(
                request_id,
                code="ask_persistence_failed",
                message="The answer could not be saved safely. Retry this Ask request.",
            ) from exc

    try:
        return record_ask_exchange(
            db,
            org_id=org_id,
            user_id=user_id,
            user_email=claims.get("email") if claims else None,
            row=exchange,
        )
    except HTTPException as exc:
        raise _ask_persistence_error(
            request_id,
            code="ask_thread_unavailable",
            message="This thread is no longer available. Refresh your threads.",
            status_code=409,
            retriable=False,
        ) from exc
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise _ask_persistence_error(
            request_id,
            code="ask_persistence_failed",
            message="The answer was generated but could not be saved. Retry this Ask request.",
        ) from exc


@router.post(
    "/ask/actions/{action_id}/confirm",
    response_model=ConfirmActionResult,
    dependencies=[Depends(rate_limit(*PROVIDER_ACTION_BUDGET))],
)
async def confirm(
    action_id: str,
    body: ConfirmActionRequest,
    db: DbSession,
    org_id: WriteOrgId,
    claims: OptionalClaims,
) -> ConfirmActionResult:
    """Execute a previously proposed agent action against its connector.

    Approval is bound to the proposing user or an org admin — any other member
    of the org is refused even with a valid action ID."""
    actor_id, is_admin = current_org_actor(db, org_id, claims)
    if claims is not None and actor_id is None:
        raise HTTPException(status_code=401, detail="Session is no longer valid.")
    return await confirm_action(
        action_id,
        body.conversation_id,
        caller_org_id=org_id,
        caller_user_id=actor_id,
        caller_is_admin=is_admin,
    )


@router.post(
    "/ask/actions/{action_id}/dismiss",
    response_model=DismissActionResult,
    dependencies=[Depends(rate_limit(*PROVIDER_ACTION_BUDGET))],
)
async def dismiss(
    action_id: str,
    _body: ConfirmActionRequest,
    db: DbSession,
    org_id: WriteOrgId,
    claims: OptionalClaims,
) -> DismissActionResult:
    """Atomically revoke a proposal for its requester or a workspace admin."""
    actor_id, is_admin = current_org_actor(db, org_id, claims)
    if claims is not None and actor_id is None:
        raise HTTPException(status_code=401, detail="Session is no longer valid.")
    return dismiss_action(
        action_id,
        caller_org_id=org_id,
        caller_user_id=actor_id,
        caller_is_admin=is_admin,
    )
