"""Data-clearance tier gating: a member only retrieves documents at or below
their clearance; admins/system context see everything."""

from __future__ import annotations

from memory.retriever import _tier_visible


def test_normal_clearance_sees_only_normal():
    assert _tier_visible("normal", "normal") is True
    assert _tier_visible("amber", "normal") is False
    assert _tier_visible("red", "normal") is False


def test_amber_clearance_sees_normal_and_amber_not_red():
    assert _tier_visible("normal", "amber") is True
    assert _tier_visible("amber", "amber") is True
    assert _tier_visible("red", "amber") is False


def test_red_clearance_sees_everything():
    for tier in ("normal", "amber", "red"):
        assert _tier_visible(tier, "red") is True


def test_missing_chunk_tier_defaults_to_normal():
    assert _tier_visible(None, "normal") is True


def test_user_clearance_admin_is_red(monkeypatch):
    """Admins always get see-all clearance regardless of their stored tier."""
    from types import SimpleNamespace

    import db.repositories as repo

    admin = SimpleNamespace(role="admin", data_tier="normal")
    member = SimpleNamespace(role="member", data_tier="amber")

    class _Session:
        def __init__(self, user):
            self._user = user

        def get(self, _model, _id):
            return self._user

    assert repo.user_clearance(_Session(admin), {"sub": "u1"}) == "red"
    assert repo.user_clearance(_Session(member), {"sub": "u2"}) == "amber"
    # No authenticated user (demo/system) → see-all.
    assert repo.user_clearance(_Session(None), None) == "red"
