# OSAI MVP Build Plan

Updated: 2026-06-04

This Markdown file is the working source of truth for the OSAI MVP.

## Build Thesis

OSAI ships as a connector-first operating layer for scattered company context and execution.
The MVP must connect painful company systems, retrieve trusted context with citations, and
execute visible downstream work with auditability.

## MVP Surfaces

- `/integrations`: connector status, auth state, scopes, last sync, sync error, sync trigger.
- `/sync-runs`: recent ingestion jobs and failures.
- `/search`: natural-language search with citations.
- `/workflows`: workflow run log.
- `/workflows/:id`: extracted items, created tasks/tickets, failures, model used.
- `/settings/data-routing`: Normal, Amber, Red data-tier routing.

## Current Stack

- Backend: Python 3.12/3.13, FastAPI, Pydantic v2, SQLAlchemy, Alembic.
- Frontend: Next.js `16.2.7`, React 19, Node 24.
- Database: PostgreSQL for pilot, SQLite used only for migration/test smoke checks.
- Vector DB: Qdrant planned next for embeddings and permission-filtered retrieval.
- Local stack: Docker Compose with API, Postgres, Redis, Qdrant.
- Connectors: direct Notion API first; Slack, Freshdesk, Google Drive registered as stubs.

## Immediate Sprint Backlog

- [x] Restore backend repo scaffold in the requested working folder.
- [x] Restore frontend dashboard scaffold.
- [x] Add Docker Compose.
- [x] Add Alembic core schema migration.
- [x] Add connector base interface.
- [x] Add connector registry.
- [x] Implement Notion connector v1.
- [x] Implement Slack connector (fixed syntax bug, full v1).
- [x] Implement Freshdesk connector v1.
- [x] Implement Google Drive connector v1.
- [x] Implement chunker.
- [x] Implement embedding pipeline (Gemini text-embedding-004 + hash fallback).
- [x] Implement Qdrant store writes.
- [x] Implement retrieval API with Gemini answer synthesis.
- [x] Implement citation UI shell.
- [x] Implement workflow runner (Gemini action-item extraction).
- [x] Implement task/ticket execution (approve → connector.execute_action).
- [x] Implement dashboard pages (all 5 wired to real API).
- [x] Add audit event records for connector syncs.
- [x] Add tests for connector contract / Notion normalization.
- [x] Add tests for DB seed and document chunk persistence.
- [x] Add Alembic migration 002 (ActionItemRecord field expansion).
- [x] Add /integrations/{key}/healthcheck endpoint.
- [x] Add /settings/data-routing endpoint (GET + PATCH).
- [x] Add /workflows/{run_id}/action-items/{item_id}/approve endpoint.
- [x] Wire workflow DB persistence (save runs + items, serve real data on GET).
- [x] Fix tsconfig.json @/* path alias for frontend.
- [x] Implement Zoom Webhook ingestion (CRC verification + signature check)
- [x] Configure Celery worker + Redis task queue
- [x] Implement download and Whisper transcription pipeline with mock fallback

## Decision Log

- 2026-06-04: Resumed environment did not expose the previously created source files; the scaffold and build plan were restored into `C:\Users\Admin\Documents\Codex\2026-06-02\files-mentioned-by-the-user-osai`.
- 2026-06-04: Notion v1 uses the direct Notion API via `httpx`, configured by `OSAI_NOTION_API_TOKEN` and optional `OSAI_NOTION_ROOT_PAGE_ID`.
- 2026-06-04: Notion sync normalizes pages into `SourceDocument`, preserves Notion page IDs as permission principals, chunks text, records sync runs, and writes connector sync audit events.
- 2026-06-04: Slack, Freshdesk, and Google Drive connectors are all fully implemented (not stubs). They will report `not_configured` until credentials are set in `.env`.
- 2026-06-04: `npm audit` still reports two moderate advisories through the current Next/PostCSS chain; keep tracking upstream patch availability.
- 2026-06-04: Added Qdrant-backed chunk upsert path with deterministic local hash embeddings for development/tests. Production embedding provider can replace the `EmbeddingProvider` interface without changing connector logic.
- 2026-06-04: Connector sync writes Postgres source/chunk records first, then attempts Qdrant vector writes. Qdrant failures are recorded on the sync run but do not block source ingestion during local pilot mode.
- 2026-06-04: Action-item approval flow: extract → `needs_review` → user approves → `connector.execute_action()` → `executed`/`skipped`. Skipped if no credentials or destination=manual.
- 2026-06-04: PyJWT added to dependencies (required by Google Drive service-account JWT signing).
- 2026-06-04: Slack _call() had a duplicate `method` parameter causing Python SyntaxError at import time — fixed.
- 2026-06-05: Configured Celery worker with Redis broker to decouple webhook ingestion from LLM processing.
- 2026-06-05: Zoom Webhook handles `endpoint.url_validation` CRC challenge response and signature verification using Webhook Secret.
- 2026-06-05: Ingest worker attempts Whisper API call for downloaded audio and falls back to a mock operations review meeting transcript when keys/downloads are absent, supporting robust local execution.
- 2026-06-05: Integrated Red-tier data routing to a local Ollama server running Llama3/Mistral, allowing offline extraction of action items.
- 2026-06-05: Hardened Celery tasks (download_and_transcribe, extract_action_items) with automatic retries, backoff, and jitter.

## Verification

- `uv run python -m pytest`: **23/23 tests passed**.
- `uv run ruff check .`: **All checks passed!**
- `npm run typecheck`: **0 errors**.
- Alembic migration 002 added for ActionItemRecord field expansion.
- `docker compose config --quiet`: passed (with Celery worker and Redis added).

## Next Slice

1. Run Compose: `docker compose up -d` (requires Docker Desktop).
2. Run `uv run alembic upgrade head` and `uv run python -m db.seed`.
3. Set credentials in `osai-backend/.env` (copy from `.env.example`).
4. `uv run uvicorn api.main:app --reload` → API at http://localhost:8000.
5. `npm run dev` in `osai-web` → Dashboard at http://localhost:3000.
6. Trigger a Notion sync via the Integrations page, then test Search.
