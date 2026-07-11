"""Shared executor for automation runs.

Both the API route (POST /automations/{id}/run) and the Celery beat scheduler
run automations through this one function, so "run now" and scheduled runs
behave identically: same run context (connected sources, new-item delta), same
executor seam (per-user Hermes sidecar if configured, else the in-house agent),
same result recording.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from agent.context import connector_context
from agent.hermes_client import run_via_hermes
from agent.orchestrator import run_ask
from api.schemas.agent import AskRequest
from db.models import Automation, User
from db.repositories import list_documents_since, record_automation_run

logger = logging.getLogger("osai.automations")


async def execute_automation(
    db: Session,
    auto: Automation,
    *,
    user_id: str | None = None,
    permissions: list[str] | None = None,
) -> dict[str, object]:
    """Run one automation and record its result. Returns the API response shape.

    When called without an explicit acting user (the scheduled path), the run
    is scoped to the automation's creator so retrieval never exceeds the access
    of the person who set it up.
    """
    user_id = user_id or auto.user_id
    if permissions is None:
        permissions = []
        if user_id:
            user = db.get(User, user_id)
            if user:
                permissions = list(user.permissions or [])

    # Run context: what's connected now, which sources were added since the last
    # run, and which documents arrived — so "summarize what's new" is answerable.
    connectors_now = await connector_context(auto.org_id)
    current_names = [
        line.split(" ", 2)[1] for line in connectors_now.splitlines() if line.startswith("- ")
    ]
    added = [n for n in current_names if n not in (auto.last_connectors or [])]
    new_docs = list_documents_since(db, auto.org_id, auto.last_run_at)
    doc_lines = [
        f"- [{source}] {title} ({ingested:%Y-%m-%d})" for source, title, ingested in new_docs
    ] or ["No new items."]
    run_context = "\n".join(
        [
            "Automation context:",
            connectors_now or "No data sources are connected yet.",
            "Connectors added since last run: " + (", ".join(added) if added else "none"),
            f"New items since last run ({auto.last_run_at or 'never'}):",
            *doc_lines,
        ]
    )

    # --- executor seam: per-user Hermes sidecar if configured, else in-house ---
    hermes = await run_via_hermes(
        auto.prompt,
        auto.org_id,
        user_id=user_id,
        permissions=permissions,
        extra_context=run_context,
    )
    if hermes is not None:
        delivery = await _deliver(auto, hermes)
        record_automation_run(db, auto.id, hermes, connectors=current_names, delivery=delivery)
        return {
            "id": auto.id, "result": hermes, "via": "hermes", "citations": [],
            "delivery": delivery,
        }
    resp = await run_ask(
        AskRequest(org_id=auto.org_id, question=f"{run_context}\n\nTask: {auto.prompt}")
    )
    delivery = await _deliver(auto, resp.answer)
    record_automation_run(db, auto.id, resp.answer, connectors=current_names, delivery=delivery)
    return {
        "id": auto.id, "result": resp.answer, "via": "osai", "citations": resp.citations,
        "delivery": delivery,
    }


async def _deliver(auto: Automation, result: str) -> dict | None:
    """Post the result to the automation's delivery target (None if unconfigured).
    The target was chosen by the user when configuring the automation — that is
    the standing approval — and failures are recorded, never raised."""
    if not auto.deliver_to:
        return None
    from agent.delivery import deliver_result

    return await deliver_result(auto.org_id, auto.deliver_to, auto.name, result)
