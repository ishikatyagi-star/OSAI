"""Real Qdrant-backed retriever with Gemini answer synthesis."""

from __future__ import annotations

import logging

import httpx

from api.schemas.search import SearchRequest, SearchResponse, SourceCitation
from config import settings
from llm.router import model_router
from memory.embeddings import EmbeddingsUnavailableError, default_embedding_provider
from memory.qdrant_store import get_default_qdrant_store
from policy import TIER_ORDER, allowed_tiers, can_access, tier_visible, visible

logger = logging.getLogger("osai.retriever")

# Data-clearance ordering (least→most sensitive). A member sees a chunk only if
# its tier is at or below their clearance; "red" clearance sees everything.
_TIER_ORDER = TIER_ORDER
_tier_visible = tier_visible
_visible = visible


async def retrieve_answer(request: SearchRequest) -> SearchResponse:
    from memory.org_memory import fetch_relevant

    qdrant = get_default_qdrant_store()

    # 0. Evolving org memory (facts/playbooks) — key-free, independent of vectors.
    memories = fetch_relevant(request.org_id, request.query)

    # 1. Vector search over the document knowledge base (best-effort).
    hits: list = []
    try:
        vectors = await default_embedding_provider.embed_texts([request.query])
        permitted_tiers = allowed_tiers(request.requester_tier)
        hits = await qdrant.search(
            vectors[0], request.org_id, limit=8, allowed_tiers=permitted_tiers
        )
    except EmbeddingsUnavailableError as exc:
        return SearchResponse(answer=str(exc), citations=[], enough_context=False)
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
        if can_access(
            (h.payload or {}).get("permissions"),
            (h.payload or {}).get("data_tier"),
            request.requester_permissions,
            request.requester_tier,
        )
    ]

    if not hits and not memories:
        return SearchResponse(
            answer="No relevant context found. Trigger a connector sync to ingest data.",
            citations=[],
            enough_context=False,
        )

    # 2. Build context snippets and citations
    context_parts: list[str] = []
    citations: list[SourceCitation] = []
    seen: set[str] = set()

    for hit in hits:
        payload = hit.payload or {}
        title = payload.get("title") or "Untitled"
        url = payload.get("url")
        source_type = payload.get("source_type", "unknown")
        text = payload.get("text") or payload.get("content_preview", "")
        doc_id = payload.get("source_document_id", "")

        context_parts.append(f"[{title}]\n{text}")

        if doc_id not in seen:
            seen.add(doc_id)
            citations.append(
                SourceCitation(
                    source_tool=source_type,
                    source_record_title=title,
                    url=url,
                    confidence=round(float(hit.score), 3),
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

    # 4. Synthesize through the central tier router. Red context is local-only;
    # a local-model outage falls back to raw grounded retrieval, never cloud.
    highest_tier = max(
        ((hit.payload or {}).get("data_tier", "normal") for hit in hits),
        key=lambda tier: _TIER_ORDER.get(tier, 0),
        default="normal",
    )
    route = model_router.route("retrieval", highest_tier)
    if route.provider == "local":
        try:
            answer = await _ollama_answer(request.query, context_text)
        except Exception:
            logger.exception("Local red-tier synthesis failed; returning grounded fallback")
            answer = _fallback_answer(memory_block, doc_titles)
    elif settings.llm_api_key or settings.gemini_api_key:
        try:
            answer = await _gemini_answer(request.query, context_text)
        except Exception:
            # Swallowed on purpose (retrieval must degrade gracefully, never
            # 500), but silent failure here is undiagnosable in prod — a bad
            # key, a rate limit, and a network error all render as the same
            # "language model is busy" text. Log the real cause.
            logger.exception("LLM synthesis failed; falling back to raw retrieval")
            answer = _fallback_answer(memory_block, doc_titles)
    else:
        answer = _fallback_answer(memory_block, doc_titles)

    return SearchResponse(
        answer=answer,
        citations=citations,
        enough_context=True,
    )


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


async def _gemini_answer(query: str, context: str) -> str:
    from llm.gemini import generate

    return await generate(_answer_prompt(query, context))


def _answer_prompt(query: str, context: str) -> str:
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


async def _ollama_answer(query: str, context: str) -> str:
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "messages": [{"role": "user", "content": _answer_prompt(query, context)}],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{settings.ollama_url.rstrip('/')}/api/chat", json=payload)
        response.raise_for_status()
    return str(response.json()["message"]["content"]).strip()
