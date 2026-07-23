"""Answer feedback — thumbs up/down with retrieval trace (the eval dataset)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.models import AnswerFeedback, utc_iso
from db.repositories import try_db
from db.session import get_db, get_optional_claims, get_org_id, require_admin, require_writable_org
from memory.org_memory import record_memory

router = APIRouter(prefix="/feedback", tags=["feedback"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Writes must never come from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]

_MAX_TEXT = 20_000


class FeedbackCreate(BaseModel):
    conversation_id: str | None = None
    query: str = Field(min_length=1, max_length=_MAX_TEXT)
    answer: str = Field(min_length=1, max_length=_MAX_TEXT)
    rating: str  # up | down
    comment: str | None = Field(default=None, max_length=2_000)
    wrong_sources: list[str] | None = None
    # "Here's the right answer" — persisted as an org-wide correction memory so
    # every future answer (whole team) can self-correct.
    correction: str | None = Field(default=None, max_length=4_000)
    # Provenance snapshot from the answer the client received: citations with
    # scores/tiers, via (osai|hermes), model_route.
    retrieval_trace: dict | None = None


@router.post("")
async def submit_feedback(
    body: FeedbackCreate, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> dict:
    if body.rating not in ("up", "down"):
        raise HTTPException(status_code=422, detail="rating must be 'up' or 'down'")

    correction = (body.correction or "").strip() or None

    def _save() -> dict:
        row = AnswerFeedback(
            org_id=org_id,
            user_id=claims.get("sub") if claims else None,
            conversation_id=body.conversation_id,
            query=body.query,
            answer=body.answer,
            rating=body.rating,
            comment=(body.comment or "").strip() or None,
            wrong_sources=body.wrong_sources or None,
            correction=correction,
            retrieval_trace=body.retrieval_trace,
        )
        db.add(row)
        db.commit()

        learned = False
        if correction and body.rating == "down":
            # Team-wide correction memory (user_id=None → org pool). Recall is
            # keyword/semantic, so include the question for future matching.
            author = (claims.get("email") or claims.get("sub")) if claims else None
            content = (
                f"Correction (from {author or 'a teammate'}): "
                f"for questions like \"{body.query.strip()}\" the correct answer is: "
                f"{correction}"
            )
            record_memory(db, org_id, "correction", content)
            learned = True
        return {"id": row.id, "recorded": True, "learned": learned}

    return try_db("submit_feedback", {"id": None, "recorded": False, "learned": False}, _save)


@router.get("")
async def list_feedback(
    db: DbSession,
    org_id: OrgId,
    _admin: Annotated[dict, Depends(require_admin)],
    rating: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Org feedback log (admin-only): the raw material for retrieval evals."""

    def _rows() -> list[dict]:
        q = (
            db.query(AnswerFeedback)
            .filter(AnswerFeedback.org_id == org_id)
            .order_by(AnswerFeedback.created_at.desc())
        )
        if rating in ("up", "down"):
            q = q.filter(AnswerFeedback.rating == rating)
        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "conversation_id": r.conversation_id,
                "query": r.query,
                "answer": r.answer,
                "rating": r.rating,
                "comment": r.comment,
                "wrong_sources": r.wrong_sources,
                "retrieval_trace": r.retrieval_trace,
                "created_at": utc_iso(r.created_at),
            }
            for r in q.limit(min(max(limit, 1), 500)).all()
        ]

    return try_db("list_feedback", [], _rows)
