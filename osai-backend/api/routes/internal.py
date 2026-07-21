"""Operational endpoints: frontend error intake and the automations cron hook.

Neither is part of the product API. The cron hook exists because the free-tier
deploy has no Celery worker — a GitHub Actions schedule (or any external cron)
POSTs it to run due automations. It authenticates with a shared secret and
404s entirely when that secret is unconfigured, so a bare deploy exposes
nothing.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from config import settings

router = APIRouter(prefix="/internal", tags=["internal"])
logger = logging.getLogger("osai.internal")

# Client errors are unauthenticated (a crash can happen before sign-in), so the
# payload is strictly shaped and size-capped — it is log fodder, never stored.
_MAX_FIELD = 4000


class ClientError(BaseModel):
    message: str = Field(max_length=_MAX_FIELD)
    stack: str = Field(default="", max_length=_MAX_FIELD)
    path: str = Field(default="", max_length=500)
    # "boundary" (route error.tsx) or "global" (global-error.tsx).
    source: str = Field(default="boundary", max_length=40)


@router.post("/client-errors")
async def report_client_error(err: ClientError) -> dict[str, bool]:
    """Frontend error boundaries report crashes here so a user-facing blank
    screen is never invisible to us. Logged always; forwarded to Sentry when
    configured."""
    logger.error(
        "client error [%s] at %s: %s\n%s", err.source, err.path, err.message, err.stack
    )
    if settings.sentry_dsn:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            scope.set_tag("origin", "web-client")
            scope.set_tag("client_path", err.path or "unknown")
            # Forward the browser stack + boundary source so Sentry can group and
            # give an actionable trace, not just the message.
            if err.source:
                scope.set_tag("client_source", err.source)
            if err.stack:
                scope.set_extra("stack", err.stack)
            sentry_sdk.capture_message(
                f"[web] {err.message}",
                level="error",
            )
    return {"ok": True}


@router.post("/automations/run-due")
async def run_due(x_cron_token: str | None = Header(default=None)) -> dict[str, object]:
    """External-cron entrypoint for scheduled automations (no worker deployed).

    Idempotent and self-advancing: each call runs only automations whose cadence
    interval has elapsed, so an aggressive or duplicated schedule cannot
    double-run anything.
    """
    if not settings.automations_cron_token:
        # Indistinguishable from a route that doesn't exist.
        raise HTTPException(status_code=404, detail="Not found")
    if not hmac.compare_digest(x_cron_token or "", settings.automations_cron_token):
        raise HTTPException(status_code=401, detail="missing/invalid X-Cron-Token")

    from agent.automation_runner import run_due_automations

    result = await run_due_automations()
    logger.info("cron run-due: ran=%s failed=%s", result["ran"], result["failed"])
    return result
