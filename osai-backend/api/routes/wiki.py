"""Org wiki — curated, versioned context that Ask cites.

Published entries are mirrored into org memory (and Supermemory when
configured), so the retriever surfaces them in answers. Suggested entries are
drafts auto-created from real work (decisions, corrections) awaiting approval.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.models import WikiEntry, WikiRevision, now_utc
from db.session import get_db, get_optional_claims, get_org_id, require_writable_org
from memory.org_memory import record_memory

router = APIRouter(prefix="/wiki", tags=["wiki"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Writes must never come from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]

_MAX = 40_000


def _row(e: WikiEntry) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "content": e.content,
        "status": e.status,
        "origin": e.origin,
        "updated_by": e.updated_by,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _index_for_ask(db: Session, e: WikiEntry) -> None:
    """Published wiki content becomes org memory so Ask can cite it."""
    record_memory(db, e.org_id, "wiki", f"{e.title}: {e.content}")


def _get(db: Session, org_id: str, entry_id: str) -> WikiEntry:
    e = db.get(WikiEntry, entry_id)
    if e is None or e.org_id != org_id:
        raise HTTPException(status_code=404, detail="Wiki entry not found.")
    return e


@router.get("")
async def list_entries(db: DbSession, org_id: OrgId) -> list[dict]:
    rows = (
        db.query(WikiEntry)
        .filter(WikiEntry.org_id == org_id)
        .order_by(WikiEntry.updated_at.desc())
        .limit(200)
        .all()
    )
    return [_row(e) for e in rows]


class EntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=_MAX)


@router.post("")
async def create_entry(
    body: EntryCreate, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> dict:
    author = (claims.get("email") or claims.get("sub")) if claims else None
    e = WikiEntry(
        org_id=org_id,
        title=body.title.strip(),
        content=body.content.strip(),
        status="published",
        origin="manual",
        updated_by=author,
    )
    db.add(e)
    db.commit()
    _index_for_ask(db, e)
    return _row(e)


class EntryPatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    content: str | None = Field(default=None, max_length=_MAX)
    # "published" approves a suggestion; no other transitions exposed.
    status: str | None = None


@router.patch("/{entry_id}")
async def update_entry(
    body: EntryPatch, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims, entry_id: str
) -> dict:
    e = _get(db, org_id, entry_id)
    author = (claims.get("email") or claims.get("sub")) if claims else None

    content_changed = (body.title and body.title.strip() != e.title) or (
        body.content and body.content.strip() != e.content
    )
    if content_changed:
        # Snapshot the pre-edit state — the revision history is the audit trail.
        db.add(
            WikiRevision(
                entry_id=e.id, org_id=org_id, title=e.title, content=e.content, author=e.updated_by
            )
        )
    if body.title:
        e.title = body.title.strip()
    if body.content:
        e.content = body.content.strip()
    approved = False
    if body.status == "published" and e.status == "suggested":
        e.status = "published"
        approved = True
    elif body.status and body.status not in ("published",):
        raise HTTPException(status_code=422, detail="status may only be set to 'published'")
    if content_changed or approved:
        e.updated_by = author
        e.updated_at = now_utc()
    db.commit()
    if e.status == "published" and (content_changed or approved):
        _index_for_ask(db, e)
    return _row(e)


@router.delete("/{entry_id}")
async def delete_entry(db: DbSession, org_id: WriteOrgId, entry_id: str) -> dict:
    e = _get(db, org_id, entry_id)
    db.query(WikiRevision).filter(WikiRevision.entry_id == e.id).delete()
    db.delete(e)
    db.commit()
    return {"deleted": True}


@router.get("/{entry_id}/revisions")
async def list_revisions(db: DbSession, org_id: OrgId, entry_id: str) -> list[dict]:
    e = _get(db, org_id, entry_id)
    rows = (
        db.query(WikiRevision)
        .filter(WikiRevision.entry_id == e.id)
        .order_by(WikiRevision.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": r.id,
            "title": r.title,
            "content": r.content,
            "author": r.author,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def suggest_entry(
    db: Session, org_id: str, title: str, content: str, origin: str
) -> WikiEntry | None:
    """Draft a wiki entry from real work (decision logged, correction given).
    Best-effort and idempotent-ish: skips when a same-title suggestion exists."""
    try:
        existing = (
            db.query(WikiEntry)
            .filter(
                WikiEntry.org_id == org_id,
                WikiEntry.title == title,
                WikiEntry.status == "suggested",
            )
            .first()
        )
        if existing:
            return None
        e = WikiEntry(
            org_id=org_id, title=title, content=content, status="suggested", origin=origin
        )
        db.add(e)
        db.commit()
        return e
    except Exception:  # noqa: BLE001 — suggestions must never break the source flow
        db.rollback()
        return None
