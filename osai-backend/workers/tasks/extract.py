"""Extraction workers tasks — extract action items from meeting transcripts."""

from __future__ import annotations

import asyncio
import logging

import httpx

from api.schemas.workflow_run import WorkflowRunCreate
from db.models import ActionItemRecord, AuditEvent, User, WorkflowRun
from db.repositories import user_clearance, user_permissions
from db.session import SessionLocal
from workers.celery_app import celery_app
from workflows.runner import run_action_item_workflow

logger = logging.getLogger("osai.tasks.extract")


@celery_app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError, RuntimeError),
    max_retries=3,
    default_retry_delay=5,
    retry_backoff=True,
    retry_jitter=True,
)
def extract_action_items(self, workflow_run_id: str) -> dict[str, str]:
    logger.info(f"Starting extraction for workflow run: {workflow_run_id}")

    with SessionLocal() as session:
        run = session.get(WorkflowRun, workflow_run_id)
        if not run:
            logger.error(f"Workflow run not found: {workflow_run_id}")
            return {"status": "failed", "error": "Workflow run not found"}

        req = WorkflowRunCreate(
            org_id=run.org_id,
            input_text=run.input_text,
            destination=run.destination,
            data_tier=run.data_tier,
        )
        actor = session.get(User, run.created_by) if run.created_by else None
        if actor is not None and actor.org_id != run.org_id:
            actor = None
        actor_claims = (
            {
                "sub": actor.id,
                "org_id": actor.org_id,
                "tv": actor.token_version or 0,
            }
            if actor is not None
            else None
        )

        # Run extraction using async helper
        try:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            response = loop.run_until_complete(
                run_action_item_workflow(
                    run_id=run.id,
                    request=req,
                    db=session,
                    requester_permissions=user_permissions(session, actor_claims),
                    requester_tier=user_clearance(session, actor_claims),
                    actor_user_id=actor.id if actor is not None else None,
                    viewer_is_admin=bool(actor is not None and actor.role == "admin"),
                )
            )
        except Exception as exc:
            logger.error(f"Error running action item extraction: {exc}")
            run.status = "failed"
            session.add(run)
            session.commit()
            return {"status": "failed", "error": str(exc)}

        # Update run status and model route
        run.status = response.status
        run.model_route = response.model_route
        session.add(run)

        # Persist extracted action items
        for item in response.action_items:
            session.add(
                ActionItemRecord(
                    workflow_run_id=run.id,
                    title=item.title,
                    owner=item.owner,
                    due_date=item.due_date,
                    source_quote=item.source_quote,
                    destination=item.destination or run.destination,
                    confidence=item.confidence,
                    status="needs_review",
                )
            )

        session.add(
            AuditEvent(
                org_id=run.org_id,
                event_type="workflow.completed",
                actor="system",
                payload={"run_id": run.id, "kind": run.kind, "status": response.status},
            )
        )
        session.commit()
        logger.info(
            f"Workflow run extraction complete: {workflow_run_id}, status: {response.status}"
        )

    return {"status": "success", "workflow_run_id": workflow_run_id}
