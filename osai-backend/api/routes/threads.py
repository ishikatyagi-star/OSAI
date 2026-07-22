"""Persisted Ask threads — the multiplayer surface.

A thread is private to its creator until shared; a shared thread is visible
and continuable by anyone in the org. @-mentions of teammates create in-app
notifications (same table as document shares).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, timedelta
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.schemas.agent import AskResponse
from db.models import AskExchange, Notification, Thread, ThreadTurn, User, now_utc, utc_iso
from db.session import get_db, get_optional_claims, get_org_id, require_writable_org

router = APIRouter(prefix="/threads", tags=["threads"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Writes must never come from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]

_MAX_TEXT = 40_000
_ASK_LEASE_SECONDS = 300


def _user(claims: dict | None) -> tuple[str | None, str | None]:
    if not claims:
        return None, None
    return claims.get("sub"), claims.get("email")


def _thread_row(t: Thread, turn_count: int | None = None) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "shared": t.shared,
        "created_by": t.created_by,
        "created_by_name": t.created_by_name,
        "created_at": utc_iso(t.created_at) if t.created_at else None,
        "updated_at": utc_iso(t.updated_at) if t.updated_at else None,
        **({"turns": turn_count} if turn_count is not None else {}),
    }


def _get_visible(db: Session, org_id: str, thread_id: str, user_id: str | None) -> Thread:
    t = db.get(Thread, thread_id)
    if t is None or t.org_id != org_id:
        raise HTTPException(status_code=404, detail="Thread not found.")
    # Private threads are creator-only; demo/system context (no user) sees all.
    if not t.shared and user_id and t.created_by and t.created_by != user_id:
        raise HTTPException(status_code=404, detail="Thread not found.")
    return t


class ThreadCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)


@router.post("")
async def create_thread(
    body: ThreadCreate, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> dict:
    user_id, email = _user(claims)
    t = Thread(org_id=org_id, created_by=user_id, created_by_name=email, title=body.title.strip())
    db.add(t)
    db.commit()
    return _thread_row(t)


@router.get("")
async def list_threads(db: DbSession, org_id: OrgId, claims: OptionalClaims) -> list[dict]:
    """The caller's own threads plus every org-shared thread."""
    user_id, _ = _user(claims)
    q = db.query(Thread).filter(Thread.org_id == org_id)
    if user_id:
        q = q.filter((Thread.shared.is_(True)) | (Thread.created_by == user_id))
    rows = q.order_by(Thread.updated_at.desc()).limit(100).all()
    ids = [t.id for t in rows]
    counts: dict[str, int] = {}
    if ids:
        counts = dict(
            db.query(ThreadTurn.thread_id, func.count(ThreadTurn.id))
            .filter(ThreadTurn.thread_id.in_(ids))
            .group_by(ThreadTurn.thread_id)
            .all()
        )
    return [_thread_row(t, counts.get(t.id, 0)) for t in rows]


@router.get("/{thread_id}")
async def get_thread(
    db: DbSession, org_id: OrgId, claims: OptionalClaims, thread_id: str
) -> dict:
    user_id, _ = _user(claims)
    t = _get_visible(db, org_id, thread_id, user_id)
    turns = (
        db.query(ThreadTurn)
        .filter(ThreadTurn.thread_id == t.id)
        .order_by(ThreadTurn.created_at.asc())
        .all()
    )
    return {
        **_thread_row(t),
        "turns": [
            {
                "id": turn.id,
                "role": turn.role,
                "content": turn.content,
                "author_name": turn.author_name,
                "payload": turn.payload,
                "created_at": utc_iso(turn.created_at) if turn.created_at else None,
            }
            for turn in turns
        ],
    }


class TurnCreate(BaseModel):
    role: str
    content: str = Field(min_length=1, max_length=_MAX_TEXT)
    payload: dict | None = None


def _exchange_turn_id(org_id: str, user_id: str, request_id: UUID, role: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"sheldon-thread-turn:{org_id}:{user_id}:{request_id}:{role}",
        )
    )


def _add_user_turn(
    db: Session,
    *,
    thread: Thread,
    org_id: str,
    user_id: str | None,
    email: str | None,
    content: str,
    turn_id: str | None = None,
) -> tuple[ThreadTurn, int]:
    if not content or len(content) > _MAX_TEXT:
        raise ValueError("User turn content is outside the persisted-thread limit.")
    turn = ThreadTurn(
        **({"id": turn_id} if turn_id else {}),
        thread_id=thread.id,
        org_id=org_id,
        role="user",
        content=content,
        author_id=user_id,
        author_name=email,
        payload=None,
    )
    db.add(turn)
    thread.updated_at = now_utc()

    mentioned: set[str] = set()
    handles = set(re.findall(r"@([\w.\-]+)", content))
    if handles:
        members = db.query(User).filter(User.org_id == org_id).all()
        for member in members:
            local = (member.email or "").split("@")[0].lower()
            name = (member.display_name or "").lower().replace(" ", "")
            if any(
                handle.lower()
                and (
                    handle.lower() == local
                    or (name and name.startswith(handle.lower()))
                )
                for handle in handles
            ) and member.id != user_id and thread.shared:
                mentioned.add(member.id)
                db.add(
                    Notification(
                        org_id=org_id,
                        user_id=member.id,
                        type="thread.mention",
                        payload={
                            "thread_id": thread.id,
                            "title": thread.title,
                            "mentioned_by": email or "A teammate",
                        },
                    )
                )
    return turn, len(mentioned)


@router.post("/{thread_id}/turns")
async def append_turn(
    body: TurnCreate, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims, thread_id: str
) -> dict:
    if body.role != "user":
        raise HTTPException(
            status_code=422,
            detail="Only user turns may be created through this endpoint.",
        )
    user_id, email = _user(claims)
    t = _get_visible(db, org_id, thread_id, user_id)
    turn, mentioned = _add_user_turn(
        db,
        thread=t,
        org_id=org_id,
        user_id=user_id,
        email=email,
        content=body.content,
    )
    db.commit()
    return {"id": turn.id, "recorded": True, "mentioned": mentioned}


def _exchange_id(org_id: str, user_id: str, request_id: UUID) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"sheldon-ask-exchange:{org_id}:{user_id}:{request_id}",
        )
    )


def reserve_ask_exchange(
    db: Session,
    *,
    org_id: str,
    user_id: str,
    request_id: UUID,
    request_payload: dict,
) -> tuple[AskExchange, bool]:
    """Durably reserve a request before any model or action-planning work."""
    row_id = _exchange_id(org_id, user_id, request_id)
    request_hash = hashlib.sha256(
        json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = db.get(AskExchange, row_id)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ask_idempotency_conflict",
                    "message": "This request ID was already used for a different Ask request.",
                    "retriable": False,
                },
            )
        return existing, False

    row = AskExchange(
        id=row_id,
        org_id=org_id,
        user_id=user_id,
        request_id=str(request_id),
        request_hash=request_hash,
        question=str(request_payload.get("question", "")),
        requested_thread_id=request_payload.get("thread_id"),
        status="running",
        lease_id=str(uuid4()),
    )
    db.add(row)
    try:
        db.commit()
        return row, True
    except IntegrityError:
        db.rollback()
        existing = db.get(AskExchange, row_id)
        if existing is None:
            raise
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ask_idempotency_conflict",
                    "message": "This request ID was already used for a different Ask request.",
                    "retriable": False,
                },
            ) from None
        return existing, False


def refresh_ask_exchange(db: Session, exchange_id: str) -> AskExchange | None:
    db.rollback()
    db.expire_all()
    return db.get(AskExchange, exchange_id)


def ask_exchange_lease_expired(row: AskExchange) -> bool:
    updated_at = row.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return updated_at <= now_utc() - timedelta(seconds=_ASK_LEASE_SECONDS)


def claim_ask_exchange(db: Session, row: AskExchange) -> tuple[AskExchange, bool]:
    reclaimable = row.status == "failed" or (
        row.status == "running" and ask_exchange_lease_expired(row)
    )
    if not reclaimable:
        return row, False
    lease_id = str(uuid4())
    updated = (
        db.query(AskExchange)
        .filter(
            AskExchange.id == row.id,
            AskExchange.status == row.status,
            AskExchange.lease_id == row.lease_id,
        )
        .update(
            {
                AskExchange.status: "running",
                AskExchange.lease_id: lease_id,
                AskExchange.response: None,
                AskExchange.thread_id: None,
                AskExchange.updated_at: now_utc(),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    current = refresh_ask_exchange(db, row.id)
    if current is None:
        raise ValueError("Ask reservation disappeared while being claimed.")
    return current, updated == 1


def store_ask_exchange_answer(
    db: Session,
    row: AskExchange,
    response: AskResponse,
) -> AskExchange:
    updated = (
        db.query(AskExchange)
        .filter(
            AskExchange.id == row.id,
            AskExchange.status == "running",
            AskExchange.lease_id == row.lease_id,
        )
        .update(
            {
                AskExchange.status: "answered",
                AskExchange.response: response.model_dump(mode="json"),
                AskExchange.updated_at: now_utc(),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    current = refresh_ask_exchange(db, row.id)
    if current is None or updated != 1:
        raise ValueError("Ask reservation lease was lost before saving the answer.")
    return current


def fail_ask_exchange(db: Session, row: AskExchange) -> None:
    try:
        (
            db.query(AskExchange)
            .filter(
                AskExchange.id == row.id,
                AskExchange.status == "running",
                AskExchange.lease_id == row.lease_id,
            )
            .update(
                {
                    AskExchange.status: "failed",
                    AskExchange.updated_at: now_utc(),
                },
                synchronize_session=False,
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def ask_exchange_response(row: AskExchange) -> AskResponse | None:
    if not isinstance(row.response, dict):
        return None
    try:
        return AskResponse.model_validate(row.response)
    except ValueError:
        return None


def load_completed_ask_exchange(
    db: Session,
    *,
    row: AskExchange,
    org_id: str,
    user_id: str,
) -> AskResponse | None:
    if row.org_id != org_id or row.user_id != user_id or row.status != "completed":
        return None
    response = ask_exchange_response(row)
    if response is None or not row.thread_id:
        return None
    thread = _get_visible(db, org_id, row.thread_id, user_id)
    response.thread_id = thread.id
    response.persistence_status = "saved"
    return response


def validate_ask_thread(db: Session, org_id: str, user_id: str, thread_id: str) -> None:
    _get_visible(db, org_id, thread_id, user_id)


def record_ask_exchange(
    db: Session,
    *,
    org_id: str,
    user_id: str,
    user_email: str | None,
    row: AskExchange,
) -> AskResponse:
    """Commit one trusted user/assistant exchange and its mentions atomically.

    This is deliberately not an HTTP route: assistant provenance comes from the
    server-side Ask execution path, never a browser-selected role or payload.
    """
    current = db.get(AskExchange, row.id)
    if current is None or current.org_id != org_id or current.user_id != user_id:
        raise ValueError("Ask reservation is unavailable.")
    existing = load_completed_ask_exchange(
        db, row=current, org_id=org_id, user_id=user_id
    )
    if existing is not None:
        return existing
    if current.status != "answered" or current.lease_id != row.lease_id:
        raise ValueError("Ask reservation is not ready to persist.")
    response = ask_exchange_response(current)
    if response is None or not response.answer or len(response.answer) > _MAX_TEXT:
        raise ValueError("Assistant turn content is outside the persisted-thread limit.")
    question = current.question
    thread_id = current.requested_thread_id
    request_id = UUID(current.request_id)
    try:
        if thread_id:
            thread = _get_visible(db, org_id, thread_id, user_id)
        else:
            thread = Thread(
                org_id=org_id,
                created_by=user_id,
                created_by_name=user_email,
                title=question.strip()[:200] or "Untitled thread",
            )
            db.add(thread)
            db.flush()

        _add_user_turn(
            db,
            thread=thread,
            org_id=org_id,
            user_id=user_id,
            email=user_email,
            content=question,
            turn_id=_exchange_turn_id(org_id, user_id, request_id, "user"),
        )
        persisted = response.model_copy(
            update={"thread_id": thread.id, "persistence_status": "saved"}
        )
        db.add(
            ThreadTurn(
                id=_exchange_turn_id(org_id, user_id, request_id, "assistant"),
                thread_id=thread.id,
                org_id=org_id,
                role="assistant",
                content=persisted.answer,
                author_id=None,
                author_name=None,
                payload={
                    "citations": [
                        citation.model_dump(mode="json")
                        for citation in persisted.citations
                    ],
                    "model_route": persisted.model_route,
                    "via": persisted.via,
                    "provenance": "server-ask",
                    "request_id": str(request_id),
                    "ask_response": persisted.model_dump(mode="json"),
                },
            )
        )
        thread.updated_at = now_utc()
        current.status = "completed"
        current.response = persisted.model_dump(mode="json")
        current.thread_id = thread.id
        current.updated_at = now_utc()
        db.commit()
        return persisted
    except IntegrityError:
        db.rollback()
        current = db.get(AskExchange, row.id)
        existing = (
            load_completed_ask_exchange(
                db, row=current, org_id=org_id, user_id=user_id
            )
            if current is not None
            else None
        )
        if existing is not None:
            return existing
        raise
    except Exception:
        db.rollback()
        raise


class ThreadPatch(BaseModel):
    shared: bool | None = None
    title: str | None = Field(default=None, max_length=300)


@router.patch("/{thread_id}")
async def update_thread(
    body: ThreadPatch, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims, thread_id: str
) -> dict:
    user_id, _ = _user(claims)
    t = _get_visible(db, org_id, thread_id, user_id)
    # Only the creator (or demo/system context) may share/rename.
    if user_id and t.created_by and t.created_by != user_id:
        raise HTTPException(status_code=403, detail="Only the thread creator can change it.")
    if body.shared is not None:
        t.shared = body.shared
    if body.title:
        t.title = body.title.strip()
    db.commit()
    return _thread_row(t)
