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
