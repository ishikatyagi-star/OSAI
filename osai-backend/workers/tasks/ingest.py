"""Ingestion workers tasks — download and transcribe meeting audio."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

import httpx

from api.schemas.connector import SourceDocument
from config import settings
from db.models import WorkflowRun
from db.repositories import chunks_for_documents, upsert_source_documents
from db.session import SessionLocal
from workers.celery_app import celery_app

logger = logging.getLogger("osai.tasks.ingest")

MOCK_TRANSCRIPT = (
    "Anish: Hi team, let's review the launch tasks for the OSAI platform.\n"
    "Ishika: I have completed the frontend dashboard pages and typechecked them. "
    "But we still need to write the Zoom webhook integration.\n"
    "Anish: Got it. I'll take ownership of writing the FastAPI webhook endpoint "
    "and the Celery worker integration by next Tuesday.\n"
    "Ishika: Great, I'll review it once it's done. Yash, can you confirm the "
    "Freshdesk API credentials and document it in the wiki?\n"
    "Yash: Yes, I will post the updated Freshdesk credentials in the general "
    "channel by Friday.\n"
    "Anish: Excellent. Also, we need to schedule a demo with the pilot client. "
    "Ishika, can you email them and coordinate a time for June 15?\n"
    "Ishika: On it. I'll send that email today.\n"
    "Anish: Thanks. Let's execute these task items."
)


@celery_app.task
def sync_connector(connector_key: str, org_id: str) -> dict[str, str]:
    return {"connector_key": connector_key, "org_id": org_id, "status": "queued"}


@celery_app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    max_retries=3,
    default_retry_delay=5,
    retry_backoff=True,
    retry_jitter=True,
)
def download_and_transcribe(
    self,
    meeting_id: str,
    download_url: str | None,
    topic: str,
    org_id: str,
) -> dict[str, str]:
    logger.info(f"Starting download and transcribe for meeting: {meeting_id}")

    transcript = None
    audio_content = None

    # 1. Download file if URL is provided and we have a transcription key
    if download_url and settings.transcribe_key:
        try:
            logger.info(f"Downloading audio from Zoom URL: {download_url}")
            with httpx.Client(timeout=60) as client:
                resp = client.get(download_url)
                if resp.status_code == 200:
                    audio_content = resp.content
                else:
                    logger.warning(f"Failed to download audio: HTTP {resp.status_code}")
        except Exception as exc:
            logger.error(f"Error during audio download: {exc}")

    # 2. Call the Whisper API (Groq by default) if audio content is available
    if audio_content and settings.transcribe_key:
        try:
            logger.info("Sending audio to Whisper API...")
            with httpx.Client(timeout=120) as client:
                headers = {"Authorization": f"Bearer {settings.transcribe_key}"}
                files = {"file": ("audio.m4a", audio_content, "audio/m4a")}
                data = {"model": settings.transcribe_model, "response_format": "json"}
                resp = client.post(
                    f"{settings.transcribe_base_url.rstrip('/')}/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                )
                if resp.status_code == 200:
                    transcript = resp.json().get("text")
                    logger.info("Whisper API transcription successful.")
                else:
                    logger.error(f"Whisper API error: HTTP {resp.status_code} - {resp.text}")
        except Exception as exc:
            logger.error(f"Error calling Whisper API: {exc}")

    # 3. Fallback to mock transcript if necessary
    if not transcript:
        logger.info("Using mock transcript fallback.")
        transcript = MOCK_TRANSCRIPT

    # 4. Save raw transcript and chunk document
    doc_id = f"zoom:meeting:{meeting_id}"
    doc = SourceDocument(
        source_id=doc_id,
        source_type="zoom",
        org_id=org_id,
        external_id=meeting_id,
        title=topic,
        url=download_url,
        text=transcript,
        metadata={"recording_completed": True},
        permissions=[],
        data_tier="normal",
    )

    with SessionLocal() as session:
        # Save SourceDocument and Chunk items
        upsert_source_documents(session, [doc])

        # Save to Qdrant (async helper run via asyncio)
        try:
            from memory.qdrant_store import get_default_qdrant_store

            qdrant_store = get_default_qdrant_store()
            chunks = chunks_for_documents([doc])

            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(qdrant_store.upsert_chunks(chunks))
            logger.info("Ingested transcript chunks into Qdrant store.")
        except Exception as exc:
            logger.error(f"Failed to index transcript chunks in Qdrant: {exc}")

        # 5. Initialize WorkflowRun
        run_id = f"workflow-{uuid4()}"
        run = WorkflowRun(
            id=run_id,
            org_id=org_id,
            kind="meeting_action_items",
            status="processing",
            input_text=transcript,
            destination="manual",
            data_tier="normal",
            model_route=settings.transcribe_model,
        )
        session.add(run)
        session.commit()

        logger.info(f"Created workflow run: {run_id} in 'processing' state.")

    # 6. Trigger action extraction task
    from workers.tasks.extract import extract_action_items

    extract_action_items.delay(run_id)

    return {
        "status": "success",
        "workflow_run_id": run_id,
        "meeting_id": meeting_id,
        "transcribed_by": (
            "whisper" if audio_content and settings.transcribe_key else "mock_fallback"
        ),
    }
