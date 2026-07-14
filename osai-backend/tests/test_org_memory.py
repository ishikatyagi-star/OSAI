"""Tests for the evolving org-memory layer (P3)."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base
from db.repositories import seed_rich_demo_data
from memory.org_memory import _tokens, derive_memories_from_data, record_memory


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_tokens_drops_stopwords_and_short():
    toks = _tokens("Who owns the Zoom webhook task?")
    assert "zoom" in toks and "webhook" in toks
    assert "who" not in toks and "the" not in toks


def test_derive_memories_creates_ownership_and_playbooks():
    session = _session()
    seed_rich_demo_data(session)
    n = derive_memories_from_data(session)
    assert n > 0
    # idempotent
    assert derive_memories_from_data(session) == 0


def test_record_memory_persists():
    session = _session()
    mem = record_memory(session, "demo-org", "decision", "We standardized on Qdrant.")
    assert mem.id
    assert "qdrant" in mem.keywords


def test_fetch_relevant_scopes_private_memories_to_owner(monkeypatch):
    """Audit Medium #10: a memory with user_id set is private to that user;
    org-wide memories (user_id None) are visible to everyone; system context
    (no requester) keeps see-all."""
    import db.session as db_session
    import memory.supermemory_client as sm
    from memory.org_memory import fetch_relevant

    # fetch_relevant consults Supermemory first and only falls through to the
    # Postgres path when it returns nothing. Stub it so this test deterministically
    # exercises the SQL visibility filter regardless of whether a live
    # OSAI_SUPERMEMORY_API_KEY is configured in the environment.
    monkeypatch.setattr(sm, "search_memories", lambda *a, **k: [])

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(db_session, "SessionLocal", factory)

    with factory() as session:
        record_memory(session, "demo-org", "fact", "Qdrant is our vector store.")
        record_memory(
            session, "demo-org", "preference", "Qdrant digests weekly for alice.",
            user_id="alice",
        )

    def _contents(user_id):
        found = fetch_relevant("demo-org", "qdrant", requester_user_id=user_id)
        return {m["content"] for m in found}

    assert _contents("alice") == {
        "Qdrant is our vector store.",
        "Qdrant digests weekly for alice.",
    }
    assert _contents("bob") == {"Qdrant is our vector store."}
    assert _contents(None) == {  # system context: see-all
        "Qdrant is our vector store.",
        "Qdrant digests weekly for alice.",
    }


def test_seeded_ownership_memories_are_org_wide():
    """Ownership facts name the owner as subject, not audience — they must not
    carry a user_id (which now means private-to)."""
    from db.models import OrgMemory

    session = _session()
    seed_rich_demo_data(session)
    derive_memories_from_data(session)
    owned = session.query(OrgMemory).filter(OrgMemory.kind == "ownership").all()
    assert owned and all(m.user_id is None for m in owned)
