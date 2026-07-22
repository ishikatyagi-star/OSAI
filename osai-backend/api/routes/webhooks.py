"""Zoom webhook placeholder.

Zoom ingestion stays unavailable until events can be bound to a verified Zoom
account and organization and recordings can be downloaded with OAuth credentials.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/zoom", include_in_schema=False)
async def zoom_webhook() -> None:
    raise HTTPException(status_code=404, detail="Not found")
