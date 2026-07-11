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


def test_person_scoped_chunk_visible_only_to_named_users():
    # Personal upload: only the uploader sees it.
    assert _visible(["user:u1"], ["user:u1"])
    assert not _visible(["user:u1"], ["user:u2"])
    # Shared with specific people: each named user sees it.
    assert _visible(["user:u1", "user:u2"], ["user:u2", "dept:eng"])


def test_person_scoped_chunk_hidden_from_admin_and_system():
    # Privacy overrides see-all: admins and system context don't read
    # a teammate's personal upload.
    assert not _visible(["user:u1"], ["role:admin"])
    assert not _visible(["user:u1"], [])
    # But an admin who is themselves a recipient still sees it.
    assert _visible(["user:u1"], ["role:admin", "user:u1"])


def test_department_grant_matches_department_members():
    assert _visible(["dept:d1"], ["user:u1", "dept:d1"])
    assert not _visible(["dept:d1"], ["user:u1", "dept:d2"])
