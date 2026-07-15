"""Liveness, readiness, and capability reporting (deployment-readiness P0).

- /health        — cheap legacy check (kept for existing monitors/uptime pings).
- /health/live   — process is up; never touches dependencies.
- /health/ready  — dependencies are usable: DB reachable, migrations at head,
                   vector store reachable. 503 with per-check detail otherwise,
                   so a deploy is not "healthy" until the org can actually use it.
- /capabilities  — which optional subsystems this deployment can actually run,
                   so the frontend can enable/disable features honestly instead
                   of assuming (e.g. recurring automation cadences).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Response
from sqlalchemy import text

from config import settings

router = APIRouter(tags=["health"])

_READY_CHECK_TIMEOUT_S = 5.0


@router.get("/")
async def root() -> dict[str, object]:
    return {
        "service": "osai-api",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "endpoints": ["/ask", "/search", "/graph/entities", "/evals", "/integrations"],
    }


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.env, "service": "osai-api"}


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    """Liveness: the process serves requests. No dependency I/O on purpose —
    a dead database must not make the orchestrator kill/restart the app."""
    return {"status": "alive", "service": "osai-api"}


def _alembic_head() -> str | None:
    """The migration head shipped with this build (None if scripts missing)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "db" / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _check_database() -> dict[str, object]:
    """DB reachable + schema at this build's migration head."""
    from db.session import SessionLocal

    with SessionLocal() as s:
        s.execute(text("SELECT 1"))
        current = s.execute(text("SELECT version_num FROM alembic_version")).scalar()
    head = _alembic_head()
    return {
        "ok": current == head and head is not None,
        "revision": current,
        "expected": head,
    }


async def _check_vector_store() -> dict[str, object]:
    from memory.qdrant_store import get_default_qdrant_store

    store = get_default_qdrant_store()
    collections = await store.client.get_collections()
    names = {c.name for c in collections.collections}
    return {"ok": True, "collection_present": store.collection_name in names}


async def _run_check(name: str, fn) -> dict[str, object]:
    """Run one readiness probe, bounded and never raising: a hung dependency
    must surface as a failed check, not a hung /health/ready."""
    try:
        if asyncio.iscoroutinefunction(fn):
            result = await asyncio.wait_for(fn(), timeout=_READY_CHECK_TIMEOUT_S)
        else:
            result = await asyncio.wait_for(
                asyncio.to_thread(fn), timeout=_READY_CHECK_TIMEOUT_S
            )
        return {"name": name, **result}
    except Exception as exc:  # noqa: BLE001 — every failure mode = not ready
        return {"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/health/ready")
async def health_ready(response: Response) -> dict[str, object]:
    """Readiness: fail (503) unless required storage and migrations are usable."""
    checks = await asyncio.gather(
        _run_check("database", _check_database),
        _run_check("vector_store", _check_vector_store),
    )
    ready = all(c.get("ok") for c in checks)
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "not_ready",
        "environment": settings.env,
        "checks": {c.pop("name"): c for c in [dict(c) for c in checks]},
    }


def _scheduler_transport_reachable() -> bool:
    """Cheap Redis ping — the celery beat/worker transport. Configuration alone
    isn't enough: a schedule accepted without a live transport will never run."""
    try:
        import redis

        client = redis.Redis.from_url(
            settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        return bool(client.ping())
    except Exception:  # noqa: BLE001 — unreachable transport = no scheduler
        return False


@router.get("/capabilities")
async def capabilities() -> dict[str, object]:
    """What this deployment can actually do. The frontend should gate recurring
    cadences, connector actions, SQL sources, and workflow execution on these
    flags instead of assuming a fully provisioned stack."""
    from connectors.composio_tool import get_default_composio_client

    scheduler = await asyncio.to_thread(_scheduler_transport_reachable)
    # Whether retrieval is actually semantic. Without a Gemini key the embedder
    # falls back to hash vectors (keyword bucketing), which answers questions
    # visibly worse while erroring nowhere — so report it rather than let it hide.
    # A non-local deploy refuses to boot in that state (see config guard); this
    # keeps it observable in local/dev, where the fallback is allowed.
    semantic_embeddings = bool(settings.gemini_api_key)
    return {
        "environment": settings.env,
        "scheduler": scheduler,
        # Manual "run now" always works; recurring cadences need the scheduler.
        "automation_cadences": ["manual"] + (["daily", "weekly"] if scheduler else []),
        "connectors": get_default_composio_client().available(),
        "sql_sources": True,  # server-side read-only SQL is built in
        "workflow_execution": bool(
            settings.hermes_sidecar_url and settings.hermes_sidecar_token
        ),
        "semantic_embeddings": semantic_embeddings,
        "embedding_model": (
            settings.gemini_embedding_model if semantic_embeddings else "hash-fallback"
        ),
        "google_oauth": settings.google_oauth_enabled,
        "email_login": bool(settings.email_login_enabled),
        "zoom_webhook": bool(settings.zoom_webhook_enabled),
    }
