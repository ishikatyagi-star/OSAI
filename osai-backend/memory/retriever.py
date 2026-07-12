"""Real Qdrant-backed retriever with Gemini answer synthesis."""

from __future__ import annotations

import logging

from api.schemas.search import SearchRequest, SearchResponse, SourceCitation
from config import settings
from llm.policy import cloud_llm_allowed, load_data_routing
from memory.embeddings import default_embedding_provider
from memory.qdrant_store import get_default_qdrant_store

logger = logging.getLogger("osai.retriever")

# Data-clearance ordering (least→most sensitive). A member sees a chunk only if
# its tier is at or below their clearance; "red" clearance sees everything.
_TIER_ORDER = {"normal": 0, "amber": 1, "red": 2}


def _tier_visible(chunk_tier: str | None, requester_tier: str) -> bool:
    return _TIER_ORDER.get(chunk_tier or "normal", 0) <= _TIER_ORDER.get(requester_tier, 2)


def _person_scoped(chunk_permissions: list[str] | None) -> bool:
    """True when a chunk is shared only with named people ("user:<id>" grants).
    Such chunks are private: they bypass admin/system see-all and are visible
    strictly to the named users — an admin shouldn't read a teammate's
    personal upload just by being admin."""
    perms = chunk_permissions or []
    return bool(perms) and all(p.startswith("user:") for p in perms)


def _visible(chunk_permissions: list[str] | None, requester_permissions: list[str]) -> bool:
    """Data-governance check. Empty/admin requester = system context (sees all),
    except person-scoped chunks, which only their named users ever see;
    otherwise a chunk is visible only if it's public or shares a permission grant."""
    chunk_permissions = chunk_permissions or []
    if _person_scoped(chunk_permissions):
        return bool(set(chunk_permissions) & set(requester_permissions))
    if not requester_permissions or "role:admin" in requester_permissions:
        return True
    if not chunk_permissions or "source:all" in chunk_permissions:
        return True
    return bool(set(chunk_permissions) & set(requester_permissions))


def _access_reason(
    chunk_permissions: list[str] | None, requester_permissions: list[str]
) -> str:
    """Human-readable reason a visible chunk passed `_visible` — mirrors its
    branches exactly, so the explanation can never disagree with the decision."""
    chunk_permissions = chunk_permissions or []
    if _person_scoped(chunk_permissions):
        if len(chunk_permissions) == 1:
            return "Private to you"
        return "Shared with you directly"
    if not requester_permissions:
        return "System context (no user restrictions apply)"
    if "role:admin" in requester_permissions:
        return "You're a workspace admin (see-all)"
    if not chunk_permissions or "source:all" in chunk_permissions:
        return "Shared with everyone in your workspace"
    shared = sorted(set(chunk_permissions) & set(requester_permissions))
    dept = [g for g in shared if g.startswith("dept:")]
    if dept:
        return "Shared with your department"
    return f"Matches your access grant: {', '.join(shared)}"


async def retrieve_answer(request: SearchRequest) -> SearchResponse:
    from memory.org_memory import fetch_relevant

    qdrant = get_default_qdrant_store()

    # 0. Evolving org memory (facts/playbooks) — key-free, independent of vectors.
    memories = fetch_relevant(
        request.org_id, request.query, requester_user_id=request.requester_user_id
    )

    # 1. Vector search over the document knowledge base (best-effort).
    hits: list = []
    try:
        vectors = await default_embedding_provider.embed_texts([request.query])
        hits = await qdrant.search(vectors[0], request.org_id, limit=8)
    except Exception:
        hits = []

    # Relevance gate: a nearest-neighbour search always returns *something*, so an
    # off-topic query would otherwise surface unrelated docs at ~0.65 confidence
    # and look like a hallucination. Keep only hits above a similarity floor.
    hits = [h for h in hits if float(getattr(h, "score", 0.0)) >= settings.retrieval_min_score]

    # Data governance: drop chunks the requester isn't permitted to see — both by
    # permission grant and by data-clearance tier (a member never sees documents
    # above their tier; admins/system context have "red" clearance = see-all).
    hits = [
        h
        for h in hits
        if _visible((h.payload or {}).get("permissions"), request.requester_permissions)
        and _tier_visible((h.payload or {}).get("data_tier"), request.requester_tier)
    ]

    # Department scope ("Ask Engineering"): keep only documents attributed to
    # the requested department. Applied after the governance filters — scoping
    # narrows visibility, never widens it.
    if request.department_id:
        hits = [
            h
            for h in hits
            if (h.payload or {}).get("department_id") == request.department_id
        ]

    if not hits and not memories:
        return SearchResponse(
            answer="No relevant context found. Trigger a connector sync to ingest data.",
            citations=[],
            enough_context=False,
        )

    # Model-egress policy: the org's data-routing settings say which tiers may
    # be sent to a cloud LLM. Partition context accordingly — restricted parts
    # only ever reach a local model (see synthesis below).
    routing = load_data_routing(request.org_id)

    # 2. Build context snippets and citations
    context_parts: list[str] = []  # cloud-eligible
    restricted_parts: list[str] = []  # local-model only, per routing policy
    citations: list[SourceCitation] = []
    seen: set[str] = set()

    for hit in hits:
        payload = hit.payload or {}
        title = payload.get("title") or "Untitled"
        url = payload.get("url")
        source_type = payload.get("source_type", "unknown")
        text = payload.get("text") or payload.get("content_preview", "")
        doc_id = payload.get("source_document_id", "")
        tier = payload.get("data_tier") or "normal"

        cloud_ok = cloud_llm_allowed(routing, tier)
        if cloud_ok:
            context_parts.append(f"[{title}]\n{text}")
        else:
            restricted_parts.append(f"[{title}]\n{text}")

        if doc_id not in seen:
            seen.add(doc_id)
            citations.append(
                SourceCitation(
                    source_tool=source_type,
                    source_record_title=title,
                    url=url,
                    confidence=round(float(hit.score), 3),
                    data_tier=tier,
                    access_reason=_access_reason(
                        payload.get("permissions"), request.requester_permissions
                    ),
                    model_routing="cloud" if cloud_ok else "local-only",
                    routing_reason=(
                        f"'{tier}' tier may be sent to cloud models"
                        if cloud_ok
                        else f"'{tier}' tier is restricted to local models by your "
                        "workspace's data-routing policy"
                    ),
                )
            )

    # Evolving memory: surface as context + citations.
    memory_lines = [f"- {m['content']}" for m in memories]
    memory_block = "\n".join(memory_lines)
    if memory_block:
        context_parts.append(f"[OSAI memory]\n{memory_block}")
        for mem in memories:
            citations.append(
                SourceCitation(
                    source_tool="memory",
                    source_record_title=mem["kind"],
                    url=None,
                    confidence=mem["score"],
                )
            )

    context_text = "\n\n---\n\n".join(context_parts)
    doc_titles = [c.source_record_title for c in citations if c.source_tool != "memory"]

    # 4. Synthesise the answer, honouring the egress policy:
    #    - restricted-tier context present → full context goes to the LOCAL
    #      model (Ollama); on local failure, cloud synthesis runs over the
    #      cloud-eligible parts only and the withholding is stated in the
    #      answer — restricted text never reaches a cloud provider.
    #    - no restricted context → cloud LLM as before, else honest fallback.
    if restricted_parts:
        full_context = "\n\n---\n\n".join(restricted_parts + context_parts)
        try:
            from llm.ollama import generate_local

            answer = await generate_local(
                _answer_prompt(request.query, full_context)
            )
        except Exception:
            logger.warning(
                "Local model unavailable; withholding %d restricted-tier snippet(s) "
                "from cloud synthesis per data-routing policy",
                len(restricted_parts),
            )
            answer = await _cloud_or_fallback(request.query, context_text, memory_block, doc_titles)
            answer += (
                f"\n\nNote: {len(restricted_parts)} document(s) in restricted data tiers "
                "were excluded from processing per your data-routing policy. Configure a "
                "local model (Ollama) or adjust Data Routing to include them."
            )
    else:
        answer = await _cloud_or_fallback(request.query, context_text, memory_block, doc_titles)

    return SearchResponse(
        answer=answer,
        citations=citations,
        enough_context=True,
    )


async def _cloud_or_fallback(
    query: str, context_text: str, memory_block: str, doc_titles: list[str]
) -> str:
    """Cloud synthesis when a provider is configured, else the honest fallback."""
    if not context_text and not memory_block:
        return _fallback_answer(memory_block, doc_titles)
    if settings.llm_api_key or settings.gemini_api_key:
        try:
            return await _gemini_answer(query, context_text)
        except Exception:
            # Swallowed on purpose (retrieval must degrade gracefully, never
            # 500), but silent failure here is undiagnosable in prod — a bad
            # key, a rate limit, and a network error all render as the same
            # "language model is busy" text. Log the real cause.
            logger.exception("LLM synthesis failed; falling back to raw retrieval")
            return _fallback_answer(memory_block, doc_titles)
    return _fallback_answer(memory_block, doc_titles)


def _fallback_answer(memory_block: str, doc_titles: list[str]) -> str:
    """Honest answer when the LLM is unavailable (rate-limited / error). Surfaces
    the real retrieved material instead of fabricating a synthesis."""
    parts: list[str] = []
    if memory_block:
        parts.append("From OSAI's memory:\n" + memory_block)
    if doc_titles:
        parts.append(
            "I found relevant documents but couldn't generate a summary right now "
            "(the language model is busy — please retry in a moment).\nSources: "
            + ", ".join(doc_titles)
        )
    return "\n\n".join(parts) if parts else (
        "I couldn't generate an answer right now (the language model is busy). "
        "Please retry in a moment."
    )


def _answer_prompt(query: str, context: str) -> str:
    """Shared synthesis prompt — identical for the cloud and local model paths
    so routing a tier locally never changes answer behaviour, only egress."""
    return (
        "You are a precise enterprise knowledge assistant for university operations. "
        "Answer the question using ONLY the provided context (documents + OSAI memory). "
        "Cite document titles inline. Be concise.\n"
        "IMPORTANT: If the context does not actually contain the answer, say plainly "
        "that you don't have that information in the connected sources — do NOT guess "
        "or invent details.\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION: {query}\n\n"
        "ANSWER:"
    )


async def _gemini_answer(query: str, context: str) -> str:
    from llm.gemini import generate

    return await generate(_answer_prompt(query, context))
