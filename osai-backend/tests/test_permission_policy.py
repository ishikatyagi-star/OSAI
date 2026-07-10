from memory.retriever import _visible


def test_source_all_grant_sees_source_scoped_documents() -> None:
    assert _visible(["source:notion"], ["source:all"])


def test_source_all_grant_does_not_bypass_role_restricted_documents() -> None:
    assert not _visible(["role:security"], ["source:all"])
