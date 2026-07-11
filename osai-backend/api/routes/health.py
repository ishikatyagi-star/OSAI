from fastapi import APIRouter

from config import settings

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
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.env, "service": "osai-api"}
