"""Real workflow runner — Gemini and local Ollama action-item extraction."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from api.schemas.workflow_run import ActionItem, WorkflowRunCreate, WorkflowRunResponse
from config import settings
from llm.policy import cloud_llm_allowed, load_data_routing
from workflows.prompts.action_items import PROMPT_VERSION, build_extraction_prompt

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("osai.workflows.runner")


async def run_action_item_workflow(
    run_id: str,
    request: WorkflowRunCreate,
    db: Session | None = None,
    requester_permissions: list[str] | None = None,
    requester_tier: str = "red",
    actor_user_id: str | None = None,
    viewer_is_admin: bool = False,
) -> WorkflowRunResponse:
    """Extract action items from meeting transcript using semantic and database context.

    Enrichment is scoped to the initiating user's permissions/clearance so the
    extraction prompt never sees documents that user couldn't retrieve. The
    system-triggered runs keep see-all document retrieval, but receive no
    user-owned action-item history unless an actor is supplied."""
    # 1. Determine query text for context lookup (first 200 chars of transcript)
    query_text = request.input_text[:200] if request.input_text else ""

    # 2. Get context (best-effort)
    context_docs = []
    existing_items = []

    from db.session import SessionLocal
    from workflows.enricher import get_workflow_context_async

    try:
        if db is not None:
            ctx = await get_workflow_context_async(
                org_id=request.org_id,
                query_text=query_text,
                session=db,
                requester_permissions=requester_permissions,
                requester_tier=requester_tier,
                actor_user_id=actor_user_id,
                viewer_is_admin=viewer_is_admin,
            )
            context_docs = ctx.get("documents", [])
            existing_items = ctx.get("action_items", [])
        else:
            with SessionLocal() as session:
                ctx = await get_workflow_context_async(
                    org_id=request.org_id,
                    query_text=query_text,
                    session=session,
                    requester_permissions=requester_permissions,
                    requester_tier=requester_tier,
                    actor_user_id=actor_user_id,
                    viewer_is_admin=viewer_is_admin,
                )
                context_docs = ctx.get("documents", [])
                existing_items = ctx.get("action_items", [])
    except Exception as exc:
        logger.error(f"Failed to fetch context for workflow {run_id}: {exc}")

    # 3. Call LLM execution path or fallback
    routing = load_data_routing(request.org_id)
    prompt_tiers = [request.data_tier, *(doc.get("data_tier") for doc in context_docs)]
    if any(not cloud_llm_allowed(routing, tier) for tier in prompt_tiers):
        return await _run_with_ollama(run_id, request, context_docs, existing_items)
    if settings.gemini_api_key:
        return await _run_with_gemini(run_id, request, context_docs, existing_items)
    return _run_fallback(run_id, request, context_docs, existing_items)


# ---------------------------------------------------------------------------
# Ollama local path
# ---------------------------------------------------------------------------


async def _run_with_ollama(
    run_id: str,
    request: WorkflowRunCreate,
    context_docs: list[dict] | None = None,
    existing_items: list[dict] | None = None,
) -> WorkflowRunResponse:
    import json
    import re

    import httpx

    prompt = build_extraction_prompt(
        request.input_text,
        request.destination,
        context_docs,
        existing_items,
    )

    url = f"{settings.ollama_url}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "format": "json",
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            content = data.get("message", {}).get("content", "")
            # Clean content from markdown code blocks
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)
            parsed = json.loads(cleaned)
            raw_items = parsed.get("items", [])
    except Exception as exc:
        logger.error(f"Error calling Ollama API for run {run_id}: {exc}")
        return WorkflowRunResponse(
            id=run_id,
            status="failed",
            model_route=f"ollama:{settings.ollama_model}:{PROMPT_VERSION}",
            action_items=[],
            audit_event_ids=[f"audit:{run_id}:ollama_error:{exc}"],
        )

    items = [
        ActionItem(
            title=str(item.get("title", ""))[:120],
            owner=item.get("owner"),
            due_date=item.get("due_date"),
            destination=item.get("destination", request.destination),  # type: ignore[arg-type]
            source_quote=item.get("source_quote"),
            confidence=float(item.get("confidence", 0.5)),
        )
        for item in raw_items
        if item.get("title")
    ]

    status = "needs_review" if items else "failed"
    return WorkflowRunResponse(
        id=run_id,
        status=status,
        model_route=f"ollama:{settings.ollama_model}:{PROMPT_VERSION}",
        action_items=items,
        audit_event_ids=[f"audit:{run_id}:created"],
    )


# ---------------------------------------------------------------------------
# Gemini path
# ---------------------------------------------------------------------------


async def _run_with_gemini(
    run_id: str,
    request: WorkflowRunCreate,
    context_docs: list[dict] | None = None,
    existing_items: list[dict] | None = None,
) -> WorkflowRunResponse:
    from llm.gemini import generate_json

    prompt = build_extraction_prompt(
        request.input_text,
        request.destination,
        context_docs,
        existing_items,
    )
    try:
        data = await generate_json(prompt)
        raw_items: list[dict] = data.get("items", [])
    except Exception as exc:
        return WorkflowRunResponse(
            id=run_id,
            status="failed",
            model_route=f"gemini:{settings.gemini_model}:{PROMPT_VERSION}",
            action_items=[],
            audit_event_ids=[f"audit:{run_id}:llm_error:{exc}"],
        )

    items = [
        ActionItem(
            title=str(item.get("title", ""))[:120],
            owner=item.get("owner"),
            due_date=item.get("due_date"),
            destination=item.get("destination", request.destination),  # type: ignore[arg-type]
            source_quote=item.get("source_quote"),
            confidence=float(item.get("confidence", 0.5)),
        )
        for item in raw_items
        if item.get("title")
    ]

    status = "needs_review" if items else "failed"
    return WorkflowRunResponse(
        id=run_id,
        status=status,
        model_route=f"gemini:{settings.gemini_model}:{PROMPT_VERSION}",
        action_items=items,
        audit_event_ids=[f"audit:{run_id}:created"],
    )


# ---------------------------------------------------------------------------
# Fallback (no API key) — simple heuristic extraction
# ---------------------------------------------------------------------------


def _run_fallback(
    run_id: str,
    request: WorkflowRunCreate,
    context_docs: list[dict] | None = None,
    existing_items: list[dict] | None = None,
) -> WorkflowRunResponse:
    items: list[ActionItem] = []
    for line in request.input_text.splitlines():
        stripped = line.strip()
        # Pick lines that look like tasks
        if stripped and any(
            stripped.lower().startswith(kw)
            for kw in ("action:", "todo:", "- [ ]", "* [ ]", "task:", "follow up")
        ):
            items.append(
                ActionItem(
                    title=stripped[:120],
                    destination=request.destination,
                    source_quote=stripped,
                    confidence=0.35,
                )
            )
    if not items:
        first_line = next((ln.strip() for ln in request.input_text.splitlines() if ln.strip()), "")
        if first_line:
            items.append(
                ActionItem(
                    title=first_line[:120],
                    destination=request.destination,
                    source_quote=first_line,
                    confidence=0.2,
                )
            )

    return WorkflowRunResponse(
        id=run_id,
        status="needs_review" if items else "failed",
        model_route="action_extraction:heuristic-fallback",
        action_items=items,
        audit_event_ids=[f"audit:{run_id}:created"],
    )
