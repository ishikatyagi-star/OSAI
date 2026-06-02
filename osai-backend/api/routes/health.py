from fastapi import APIRouter

from config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.env,
        "service": "osai-api",
    }
