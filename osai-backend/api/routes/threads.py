"""Persisted Ask threads — the multiplayer surface.

A thread is private to its creator until shared; a shared thread is visible
and continuable by anyone in the org. @-mentions of teammates create in-app
notifications (same table as document shares).
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import Notification, Thread, ThreadTurn, User, now_utc
from db.session import get_db, get_optional_claims, get_org_id, require_writable_org

router = APIRouter(prefix="/threads", tags=["threads"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Writes must never come from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]

_MAX_TEXT = 40_000


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
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
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
                "created_at": turn.created_at.isoformat() if turn.created_at else None,
            }
            for turn in turns
        ],
    }


class TurnCreate(BaseModel):
    role: str
    content: str = Field(min_length=1, max_length=_MAX_TEXT)
    payload: dict | None = None


@router.post("/{thread_id}/turns")
async def append_turn(
    body: TurnCreate, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims, thread_id: str
) -> dict:
    if body.role not in ("user", "assistant"):
        raise HTTPException(status_code=422, detail="role must be 'user' or 'assistant'")
    user_id, email = _user(claims)
    t = _get_visible(db, org_id, thread_id, user_id)
    turn = ThreadTurn(
        thread_id=t.id,
        org_id=org_id,
        role=body.role,
        content=body.content,
        author_id=user_id if body.role == "user" else None,
        author_name=email if body.role == "user" else None,
        payload=body.payload,
    )
    db.add(turn)
    t.updated_at = now_utc()

    # @-mentions in user turns notify matching teammates (by display name or
    # email local-part), so a shared thread can pull someone in.
    mentioned: list[str] = []
    if body.role == "user":
        handles = set(re.findall(r"@([\w.\-]+)", body.content))
        if handles:
            members = db.query(User).filter(User.org_id == org_id).all()
            for m in members:
                local = (m.email or "").split("@")[0].lower()
                name = (m.display_name or "").lower().replace(" ", "")
                for h in handles:
                    hl = h.lower()
                    if hl and (hl == local or (name and name.startswith(hl))) and m.id != user_id:
                        mentioned.append(m.id)
                        db.add(
                            Notification(
                                org_id=org_id,
                                user_id=m.id,
                                type="thread.mention",
                                payload={
                                    "thread_id": t.id,
                                    "title": t.title,
                                    "mentioned_by": email or "A teammate",
                                },
                            )
                        )
                        break
    db.commit()
    return {"id": turn.id, "recorded": True, "mentioned": len(set(mentioned))}


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
