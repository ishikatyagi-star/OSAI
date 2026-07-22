"""Model-egress policy: restricted-tier content must never reach cloud LLMs.

Covers llm/policy.py decisions and the retriever's enforcement (local-model
routing, withholding on local failure) plus the Hermes context filter.
"""

from __future__ import annotations

from types import SimpleNamespace

from api.schemas.search import SearchRequest
from config import settings
from llm.policy import (
    DEFAULT_DATA_ROUTING,
    cloud_llm_allowed,
    connector_egress_allowed,
)

# --- policy decisions -------------------------------------------------------


def test_default_policy_allows_normal_blocks_amber_red():
    assert cloud_llm_allowed(DEFAULT_DATA_ROUTING, "normal") is True
    assert cloud_llm_allowed(DEFAULT_DATA_ROUTING, "amber") is False
    assert cloud_llm_allowed(DEFAULT_DATA_ROUTING, "red") is False


def test_unknown_tier_is_denied():
    assert cloud_llm_allowed(DEFAULT_DATA_ROUTING, "ultraviolet") is False


def test_missing_tier_is_denied():
    assert cloud_llm_allowed(DEFAULT_DATA_ROUTING, None) is False


def test_org_override_can_allow_amber():
    routing = {
        **DEFAULT_DATA_ROUTING,
        "amber": {**DEFAULT_DATA_ROUTING["amber"], "llm_allowed": True},
    }
    assert cloud_llm_allowed(routing, "amber") is True


def test_connector_egress_requires_provenance_and_every_tier_allowlist():
    assert connector_egress_allowed(DEFAULT_DATA_ROUTING, [], "slack") is False
    assert connector_egress_allowed(DEFAULT_DATA_ROUTING, [None], "slack") is False
    assert connector_egress_allowed(DEFAULT_DATA_ROUTING, ["normal"], "slack") is True
    assert connector_egress_allowed(DEFAULT_DATA_ROUTING, ["normal", "amber"], "slack") is False


# --- retriever enforcement --------------------------------------------------


def _hit(text: str, tier: str, doc_id: str, title: str = "Doc"):
    return SimpleNamespace(
        score=0.9,
        payload={
            "title": title,
            "text": text,
            "source_type": "notion",
            "source_document_id": doc_id,
            "data_tier": tier,
            "permissions": ["source:all"],
        },
    )


def _patch_retrieval(monkeypatch, hits):
    import memory.org_memory as org_memory
    import memory.retriever as retriever

    class _FakeStore:
        async def search(self, vector, org_id, limit=8):
            return hits

    class _FakeEmbeddings:
        async def embed_texts(self, texts):
            return [[0.0] * 8]

    monkeypatch.setattr(retriever, "get_default_qdrant_store", lambda: _FakeStore())
    monkeypatch.setattr(retriever, "default_embedding_provider", _FakeEmbeddings())
    monkeypatch.setattr(
        retriever, "_authoritative_document_hits", lambda candidate_hits, _org_id: candidate_hits
    )
    monkeypatch.setattr(org_memory, "fetch_relevant", lambda org_id, q, **kw: [])
    monkeypatch.setattr(
        retriever, "load_data_routing", lambda org_id: DEFAULT_DATA_ROUTING
    )
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")


async def test_red_content_goes_to_local_model_not_cloud(monkeypatch):
    from memory.retriever import retrieve_answer

    hits = [
        _hit("public info", "normal", "d1"),
        _hit("SECRET launch codes", "red", "d2", title="Secrets"),
    ]
    _patch_retrieval(monkeypatch, hits)

    cloud_prompts: list[str] = []
    local_prompts: list[str] = []

    async def fake_cloud(prompt, model=None):
        cloud_prompts.append(prompt)
        return "cloud answer"

    async def fake_local(prompt, timeout=60.0):
        local_prompts.append(prompt)
        return "local answer"

    import llm.gemini
    import llm.ollama

    monkeypatch.setattr(llm.gemini, "generate", fake_cloud)
    monkeypatch.setattr(llm.ollama, "generate_local", fake_local)

    res = await retrieve_answer(SearchRequest(org_id="demo-org", query="launch?"))

    assert res.answer == "local answer"
    assert cloud_prompts == []  # nothing left the building
    assert any("SECRET launch codes" in p for p in local_prompts)
    # Citations still visible to the (cleared) user, tier-tagged.
    tiers = {c.data_tier for c in res.citations}
    assert tiers == {"normal", "red"}


async def test_local_failure_withholds_restricted_from_cloud(monkeypatch):
    from memory.retriever import retrieve_answer

    hits = [
        _hit("public info", "normal", "d1"),
        _hit("SECRET launch codes", "red", "d2"),
    ]
    _patch_retrieval(monkeypatch, hits)

    cloud_prompts: list[str] = []

    async def fake_cloud(prompt, model=None):
        cloud_prompts.append(prompt)
        return "cloud answer"

    async def fake_local(prompt, timeout=60.0):
        raise ConnectionError("ollama down")

    import llm.gemini
    import llm.ollama

    monkeypatch.setattr(llm.gemini, "generate", fake_cloud)
    monkeypatch.setattr(llm.ollama, "generate_local", fake_local)

    res = await retrieve_answer(SearchRequest(org_id="demo-org", query="launch?"))

    # Cloud saw only the normal-tier snippet; the red one was withheld and the
    # answer says so.
    assert cloud_prompts and all("SECRET" not in p for p in cloud_prompts)
    assert any("public info" in p for p in cloud_prompts)
    assert "excluded from processing" in res.answer


async def test_all_normal_content_uses_cloud_as_before(monkeypatch):
    from memory.retriever import retrieve_answer

    _patch_retrieval(monkeypatch, [_hit("public info", "normal", "d1")])

    async def fake_cloud(prompt, model=None):
        return "cloud answer"

    import llm.gemini

    monkeypatch.setattr(llm.gemini, "generate", fake_cloud)

    res = await retrieve_answer(SearchRequest(org_id="demo-org", query="q"))
    assert res.answer == "cloud answer"


# --- Hermes context filter ---------------------------------------------------


async def test_hermes_context_drops_restricted_snippets(monkeypatch):
    from agent import hermes_client
    from api.schemas.search import SearchResponse, SourceCitation

    async def fake_retrieve(request):
        return SearchResponse(
            answer="SECRET synthesized from restricted context",
            citations=[
                SourceCitation(
                    source_tool="notion",
                    source_record_title="Public doc",
                    data_tier="normal",
                ),
                SourceCitation(
                    source_tool="drive",
                    source_record_title="Red doc",
                    data_tier="red",
                ),
            ],
            enough_context=True,
        )

    monkeypatch.setattr(hermes_client, "retrieve_answer", fake_retrieve)
    import llm.policy as policy

    monkeypatch.setattr(policy, "load_data_routing", lambda org_id: DEFAULT_DATA_ROUTING)

    ctx = await hermes_client._permitted_context(
        "q",
        "demo-org",
        [],
        requester_tier="red",
        requester_user_id=None,
    )
    assert "notion" in ctx
    assert "drive" not in ctx
    assert "SECRET" not in ctx


async def test_hermes_context_keeps_answer_when_all_context_is_egress_safe(monkeypatch):
    from agent import hermes_client
    from api.schemas.search import SearchResponse, SourceCitation

    async def fake_retrieve(request):
        return SearchResponse(
            answer="safe synthesized answer",
            citations=[
                SourceCitation(
                    source_tool="notion",
                    source_record_title="Safe doc",
                    data_tier="normal",
                )
            ],
            enough_context=True,
        )

    monkeypatch.setattr(hermes_client, "retrieve_answer", fake_retrieve)
    import llm.policy as policy

    monkeypatch.setattr(policy, "load_data_routing", lambda org_id: DEFAULT_DATA_ROUTING)
    ctx = await hermes_client._permitted_context(
        "q",
        "demo-org",
        [],
        requester_tier="normal",
        requester_user_id=None,
    )
    assert "safe synthesized answer" in ctx


async def test_hermes_checks_restricted_citations_beyond_snippet_cap(monkeypatch):
    from agent import hermes_client
    from api.schemas.search import SearchResponse, SourceCitation

    async def fake_retrieve(request):
        return SearchResponse(
            answer="SECRET derived from the sixth citation",
            citations=[
                *[
                    SourceCitation(
                        source_tool=f"normal-{index}",
                        source_record_title=f"Normal {index}",
                        data_tier="normal",
                    )
                    for index in range(5)
                ],
                SourceCitation(
                    source_tool="restricted-sixth",
                    source_record_title="Restricted sixth",
                    data_tier="red",
                ),
            ],
            enough_context=True,
        )

    monkeypatch.setattr(hermes_client, "retrieve_answer", fake_retrieve)
    import llm.policy as policy

    monkeypatch.setattr(policy, "load_data_routing", lambda org_id: DEFAULT_DATA_ROUTING)
    ctx = await hermes_client._permitted_context(
        "q",
        "demo-org",
        [],
        requester_tier="red",
        requester_user_id=None,
    )
    assert "SECRET" not in ctx
    assert "restricted-sixth" not in ctx
