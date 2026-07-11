"""Graph ACL regression tests (audit High #2).

The /graph endpoints expose document titles and content previews, so the
Postgres provider must apply the same governance rule as retrieval: a member
only sees source nodes for documents they hold a permission grant for, at or
below their clearance tier. Admin/system context keeps see-all behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace

from graph.provider import build_graph


def _doc(doc_id: str, permissions: list[str] | None, tier: str = "normal"):
    return SimpleNamespace(
        id=doc_id,
        title=f"Doc {doc_id}",
        text="secret contents " * 20,
        url=None,
        source_type="notion",
        permissions=permissions,
        data_tier=tier,
    )


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _Session:
    """Returns docs for SourceDocumentRecord queries, nothing for the rest."""

    def __init__(self, docs):
        self._docs = docs

    def query(self, model):
        if model.__name__ == "SourceDocumentRecord":
            return _Query(self._docs)
        return _Query([])


_DOCS = [
    _doc("open", permissions=["source:all"]),
    _doc("slack-only", permissions=["source:slack"]),
    _doc("red-doc", permissions=["source:all"], tier="red"),
]


def _source_ids(entities):
    return {e.id for e in entities if e.type == "source"}


def test_member_only_sees_granted_docs_at_their_tier():
    entities, _ = build_graph(
        _Session(_DOCS),
        "org-1",
        requester_permissions=["source:notion"],
        requester_tier="normal",
    )
    assert _source_ids(entities) == {"source:open"}


def test_member_with_grant_sees_matching_doc():
    entities, _ = build_graph(
        _Session(_DOCS),
        "org-1",
        requester_permissions=["source:slack"],
        requester_tier="amber",
    )
    assert _source_ids(entities) == {"source:open", "source:slack-only"}


def test_admin_and_system_context_see_everything():
    for perms in (["role:admin"], []):
        entities, _ = build_graph(
            _Session(_DOCS), "org-1", requester_permissions=perms, requester_tier="red"
        )
        assert _source_ids(entities) == {
            "source:open",
            "source:slack-only",
            "source:red-doc",
        }


def test_red_doc_withheld_below_red_clearance():
    entities, _ = build_graph(
        _Session(_DOCS),
        "org-1",
        requester_permissions=["role:admin"],
        requester_tier="amber",
    )
    assert "source:red-doc" not in _source_ids(entities)
