"""Evolving agent/org memory — facts, decisions, resolutions, playbooks.

This is the layer the knowledge base (Qdrant docs) is NOT: it captures what the
org knows and how it tends to act, and is injected into answers so OSAI is
visibly stateful. Relevance is a lightweight keyword overlap (deterministic, no
embedding key needed); it can be upgraded to vector recall later.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from db.models import ActionItemRecord, OrgMemory, WorkflowRun

_STOPWORDS = {
    "who", "the", "a", "an", "is", "are", "was", "were", "what", "how", "do",
    "does", "for", "and", "to", "of", "in", "on", "with", "should", "be", "done",
    "by", "this", "that", "it", "we", "our", "i", "you", "they",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"\w+", (text or "").lower())
    return {t for t in words if len(t) > 2 and t not in _STOPWORDS}


def record_memory(
    session: Session,
    org_id: str,
    kind: str,
    content: str,
    *,
    user_id: str | None = None,
    source_run_id: str | None = None,
    keywords: list[str] | None = None,
) -> OrgMemory:
    mem = OrgMemory(
        org_id=org_id,
        user_id=user_id,
        kind=kind,
        content=content,
        keywords=keywords or sorted(_tokens(content)),
        source_run_id=source_run_id,
    )
    session.add(mem)
    session.commit()
    # Dual-write to Supermemory when configured — Postgres stays the durable
    # source of truth; Supermemory adds semantic recall across the same pool.
    from memory import supermemory_client

    supermemory_client.add_memory(org_id, content, user_id=user_id, kind=kind)
    return mem


def fetch_relevant(
    org_id: str,
    query: str,
    limit: int = 5,
    requester_user_id: str | None = None,
) -> list[dict]:
    """Top memories for a query by keyword overlap. Opens its own session so
    callers (retriever, agent) don't need to thread one through.

    Visibility: `user_id` on a memory marks it as private to that user, so recall
    returns org-wide memories (user_id NULL) plus the requester's own. A None
    requester is system context (webhook/demo) and keeps see-all, matching the
    governance stance everywhere else. Memories carry no data tier — they are
    distilled facts/playbooks, not document content — so there is no tier check."""
    from db.session import SessionLocal
    from memory import supermemory_client

    # Prefer Supermemory's semantic recall when configured; its container tags
    # (org:/user:) encode the same visibility split enforced below for the
    # Postgres path. Empty result (disabled or failure) falls through.
    sm = supermemory_client.search_memories(
        org_id, query, requester_user_id=requester_user_id, limit=limit
    )
    if sm:
        return sm

    q_tokens = _tokens(query)
    if not q_tokens:
        return []
    try:
        with SessionLocal() as session:
            q = session.query(OrgMemory).filter(OrgMemory.org_id == org_id)
            if requester_user_id is not None:
                q = q.filter(
                    (OrgMemory.user_id.is_(None))
                    | (OrgMemory.user_id == requester_user_id)
                )
            memories = q.all()
            scored = []
            for mem in memories:
                bag = set(mem.keywords or []) | _tokens(mem.content)
                overlap = len(q_tokens & bag)
                if overlap:
                    scored.append((overlap, mem))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                {
                    "id": mem.id,
                    "kind": mem.kind,
                    "content": mem.content,
                    "score": round(score / max(len(q_tokens), 1), 3),
                }
                for score, mem in scored[:limit]
            ]
    except Exception:
        return []


# Ops playbooks — how the org tends to handle recurring situations.
_PLAYBOOKS: list[tuple[str, list[str]]] = [
    (
        "Broken or malfunctioning equipment (projectors, AV, hardware) should be "
        "logged as a Freshdesk support ticket and routed to facilities.",
        ["broken", "malfunction", "equipment", "projector", "av", "hardware",
         "ticket", "repair", "facilities", "room"],
    ),
    (
        "Urgent support requests are escalated to the operations team within a "
        "4-hour SLA and announced in the Slack #operations channel.",
        ["urgent", "escalate", "sla", "support", "operations", "slack"],
    ),
]


def derive_memories_from_data(session: Session, org_id: str = "demo-org") -> int:
    """Seed org memory from existing records (ownership facts) + ops playbooks.
    Idempotent: no-ops if the org already has memories."""
    if session.query(OrgMemory).filter(OrgMemory.org_id == org_id).count() > 0:
        return 0

    created = 0
    # Ownership facts from action items.
    items = (
        session.query(ActionItemRecord)
        .join(WorkflowRun, ActionItemRecord.workflow_run_id == WorkflowRun.id)
        .filter(WorkflowRun.org_id == org_id)
        .all()
    )
    for item in items:
        if not item.owner:
            continue
        content = f"{item.owner} owns the task: {item.title}"
        session.add(
            OrgMemory(
                org_id=org_id,
                # Ownership facts are org-wide knowledge — the owner is the
                # *subject*, not the audience, so user_id (= private-to) stays
                # empty. Setting it would hide "who owns X" from everyone else.
                user_id=None,
                kind="ownership",
                content=content,
                keywords=sorted(_tokens(item.title) | {item.owner.split("@")[0]}),
            )
        )
        created += 1

    for content, keywords in _PLAYBOOKS:
        session.add(
            OrgMemory(org_id=org_id, kind="playbook", content=content, keywords=keywords)
        )
        created += 1

    session.commit()
    return created
