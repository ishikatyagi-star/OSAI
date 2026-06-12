"""Permission-aware retrieval (data governance)."""

from __future__ import annotations

from memory.retriever import _visible


def test_admin_or_system_context_sees_everything():
    # Empty requester perms == internal/system context.
    assert _visible(["role:security"], [])
    assert _visible(["role:security"], ["role:admin"])


def test_public_chunks_visible_to_anyone():
    assert _visible(["source:all"], ["role:other"])
    assert _visible([], ["role:other"])
    assert _visible(None, ["role:other"])


def test_restricted_chunk_requires_matching_grant():
    assert not _visible(["role:security"], ["role:other"])
    assert _visible(["role:security"], ["role:security"])
    assert _visible(["role:security"], ["role:hr", "role:security"])
