"""Zoom Webhook route — handles Zoom CRC validation and recording events."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from config import settings
from db.session import get_db
from workers.tasks.ingest import download_and_transcribe

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger("osai.webhooks")
DbSession = Annotated[Session, Depends(get_db)]


def verify_zoom_signature(
    request_timestamp: str,
    signature: str,
    raw_body: bytes,
    secret: str | None,
) -> bool:
    """Verify Zoom webhook event signature using Webhook Secret Token.

    Fail closed: with no configured secret we cannot authenticate the caller, so
    the event is rejected rather than trusted (SEC-004). The route additionally
    requires a secret whenever the webhook is enabled (see config validator), so
    in a correctly configured deployment this branch is never reached."""
    if not secret:
        logger.error("OSAI_ZOOM_WEBHOOK_SECRET is not configured; rejecting webhook event.")
        return False

    # Construct the message string: v0:{timestamp}:{raw_body}
    message = f"v0:{request_timestamp}:{raw_body.decode('utf-8')}"

    # Compute HMAC SHA-256
    computed_hash = hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    expected_signature = f"v0={computed_hash}"
    return hmac.compare_digest(expected_signature, signature)


@router.post("/zoom")
async def zoom_webhook(
    request: Request,
    db: DbSession,
    x_zm_signature: Annotated[str | None, Header()] = None,
    x_zm_request_timestamp: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """Handle incoming Zoom webhooks (endpoint validation & events)."""
    # Feature-flagged off by default. While disabled the endpoint does not exist
    # (404) rather than accepting events — ingestion is still demo-org-only and
    # the transcription task has no worker in prod, so exposing it is all risk,
    # no delivery. Flip OSAI_ZOOM_WEBHOOK_ENABLED (with a secret) to turn it on.
    if not settings.zoom_webhook_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    raw_body = await request.body()
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    event = payload.get("event")

    # 1. Endpoint URL Validation Challenge (CRC)
    if event == "endpoint.url_validation":
        plain_token = payload.get("payload", {}).get("plainToken")
        if not plain_token:
            raise HTTPException(status_code=400, detail="Missing plainToken for URL validation")

        secret = settings.zoom_webhook_secret or ""
        # Compute HMAC SHA-256 encryptedToken using the webhook secret
        hash_object = hmac.new(secret.encode("utf-8"), plain_token.encode("utf-8"), hashlib.sha256)
        encrypted_token = hash_object.hexdigest()

        logger.info("Zoom endpoint validation challenge successful.")
        return {
            "plainToken": plain_token,
            "encryptedToken": encrypted_token,
        }

    # 2. Signature verification for standard webhook events
    if settings.zoom_webhook_secret:
        if not x_zm_signature or not x_zm_request_timestamp:
            raise HTTPException(status_code=401, detail="Missing verification headers")

        if not verify_zoom_signature(
            x_zm_request_timestamp,
            x_zm_signature,
            raw_body,
            settings.zoom_webhook_secret,
        ):
            raise HTTPException(status_code=401, detail="Invalid signature")

    # 3. Handle Zoom events
    if event == "recording.completed":
        event_payload = payload.get("payload", {})
        meeting_obj = event_payload.get("object", {})
        meeting_id = str(meeting_obj.get("id", ""))
        topic = meeting_obj.get("topic", "Zoom Meeting")
        recording_files = meeting_obj.get("recording_files", [])

        if not meeting_id:
            raise HTTPException(status_code=400, detail="Missing meeting ID")

        # Prioritize audio files (type M4A or MP3) for transcription
        audio_file = None
        for f in recording_files:
            file_type = str(f.get("file_type", "")).upper()
            if file_type in ("M4A", "MP3"):
                audio_file = f
                break

        # Fallback to any file with download_url if no audio-only exists
        if not audio_file and recording_files:
            audio_file = recording_files[0]

        download_url = audio_file.get("download_url") if audio_file else None

        logger.info(
            f"Zoom meeting recording completed event received. Meeting ID: {meeting_id}, "
            f"Topic: {topic}, Download URL: {download_url}"
        )

        # Trigger background Celery ingestion task
        download_and_transcribe.delay(
            meeting_id=meeting_id,
            download_url=download_url,
            topic=topic,
            org_id=settings.default_org_id,
        )

    return {"status": "ok"}
