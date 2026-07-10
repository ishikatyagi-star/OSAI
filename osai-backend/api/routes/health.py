import asyncio

import httpx
import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from config import settings
from db.session import SessionLocal

router = APIRouter(tags=["health"])


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
async def health() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - health responses must not expose internals
        checks["database"] = "unavailable"

    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f"{settings.qdrant_url.rstrip('/')}/collections")
            response.raise_for_status()
        checks["qdrant"] = "ok"
    except Exception:  # noqa: BLE001
        checks["qdrant"] = "unavailable"

    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        await asyncio.to_thread(client.ping)
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "unavailable"

    healthy = all(status == "ok" for status in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "environment": settings.env,
            "service": "osai-api",
            "checks": checks,
        },
    )
