"""Liveness, readiness, and capability reporting (deployment-readiness P0).

- /health        — cheap legacy check (kept for existing monitors/uptime pings).
- /health/live   — process is up; never touches dependencies.
- /health/ready  — dependencies are usable: DB reachable, migrations at head,
                   vector store reachable, and Redis can execute Lua. 503 with
                   per-check detail otherwise, so a deploy is not "healthy"
                   until the org can actually use it.
- /capabilities  — which optional subsystems this deployment can actually run,
                   so the frontend can enable/disable features honestly instead
                   of assuming (e.g. recurring automation cadences).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Response
from sqlalchemy import text

from config import settings

router = APIRouter(tags=["health"])
logger = logging.getLogger("osai.health")

_READY_CHECK_TIMEOUT_S = 5.0


def _build_sha() -> str:
    """Public deploy identity. Render supplies its commit SHA automatically;
    other hosts can set the portable OSAI_BUILD_SHA fallback."""
    return os.getenv("RENDER_GIT_COMMIT") or os.getenv("OSAI_BUILD_SHA") or "unknown"


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
    return {
        "status": "ok",
        "environment": settings.env,
        "service": "osai-api",
        "build_sha": _build_sha(),
    }


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    """Liveness: the process serves requests. No dependency I/O on purpose —
    a dead database must not make the orchestrator kill/restart the app."""
    return {"status": "alive", "service": "osai-api", "build_sha": _build_sha()}


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


async def _check_redis() -> dict[str, object]:
    """Prove the rate limiter's required Redis EVAL path is usable."""
    from api.ratelimit import _get_redis_client

    result = await _get_redis_client().eval("return redis.call('PING')", 0)
    return {"ok": result in {b"PONG", "PONG"}}


async def _run_check(name: str, fn) -> dict[str, object]:
    """Run one readiness probe, bounded and never raising: a hung dependency
    must surface as a failed check, not a hung /health/ready."""
    try:
        if inspect.iscoroutinefunction(fn):
            result = await asyncio.wait_for(fn(), timeout=_READY_CHECK_TIMEOUT_S)
        else:
            result = await asyncio.wait_for(asyncio.to_thread(fn), timeout=_READY_CHECK_TIMEOUT_S)
        return {"name": name, **result}
    except TimeoutError:
        logger.warning("readiness check timed out: %s", name)
        return {"name": name, "ok": False, "error": "timeout"}
    except Exception:  # noqa: BLE001 — every failure mode = not ready
        # Dependency errors often contain DSNs, hostnames, or provider details.
        # Keep those in server logs and expose only a stable public status.
        logger.warning("readiness check failed: %s", name, exc_info=True)
        return {"name": name, "ok": False, "error": "dependency_unavailable"}


@router.get("/health/ready")
async def health_ready(response: Response) -> dict[str, object]:
    """Readiness: fail (503) unless required storage and migrations are usable."""
    checks = await asyncio.gather(
        _run_check("database", _check_database),
        _run_check("vector_store", _check_vector_store),
        _run_check("redis", _check_redis),
    )
    ready = all(c.get("ok") for c in checks)
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "not_ready",
        "environment": settings.env,
        "build_sha": _build_sha(),
        "checks": {c.pop("name"): c for c in [dict(c) for c in checks]},
    }


def _scheduler_available() -> bool:
    """Whether beat and the automation queue recently reached a worker."""
    from workers.scheduler_health import scheduler_available

    return scheduler_available()


@router.get("/capabilities")
async def capabilities() -> dict[str, object]:
    """What this deployment can actually do. The frontend should gate recurring
    cadences, connector actions, SQL sources, and workflow execution on these
    flags instead of assuming a fully provisioned stack."""
    from connectors.composio_tool import get_default_composio_client

    scheduler = await asyncio.to_thread(_scheduler_available)
    # Whether retrieval is actually semantic. Report from the *active* embedding
    # provider, not from whichever key happens to be set: Jina/Voyage take
    # precedence over Gemini, so a Gemini-key-only check would misname the model
    # in use. Without any provider key the embedder falls back to hash vectors
    # (keyword bucketing), which answers visibly worse while erroring nowhere; a
    # non-local deploy refuses to boot in that state (see config guard), so this
    # is observable mainly in local/dev where the fallback is allowed.
    from memory.embeddings import HashEmbeddingProvider, default_embedding_provider

    semantic_embeddings = not isinstance(default_embedding_provider, HashEmbeddingProvider)
    return {
        "environment": settings.env,
        "scheduler": scheduler,
        # Manual "run now" always works; recurring cadences need the scheduler.
        "automation_cadences": ["manual"] + (["hourly", "daily", "weekly"] if scheduler else []),
        "connectors": get_default_composio_client().available(),
        "sql_sources": True,  # server-side read-only SQL is built in
        "workflow_execution": bool(settings.hermes_sidecar_url and settings.hermes_sidecar_token),
        "semantic_embeddings": semantic_embeddings,
        "embedding_model": getattr(default_embedding_provider, "model", "hash-fallback"),
        "google_oauth": settings.google_oauth_enabled,
        "email_login": bool(settings.email_login_enabled),
        "zoom_webhook": False,
    }
