# OSAI

AI-native operations layer for universities — a **company brain + reasoning + action** system. Connect your tools, ask anything, and let OSAI retrieve, remember, and take action.

> Planning docs: [`OSAI_EXECUTION_PLAN.md`](OSAI_EXECUTION_PLAN.md) (what/how), [`OSAI_PARALLEL_PLAN.md`](OSAI_PARALLEL_PLAN.md) (who/when), [`OSAI_BUILD_ROADMAP.md`](OSAI_BUILD_ROADMAP.md) (summary).

## Architecture

```
osai-backend/   FastAPI · SQLAlchemy · Qdrant (RAG) · Gemini/OpenRouter (LLM) · Celery
osai-web/       Next.js frontend (chat, graph inspector, eval dashboard, connectors)
services/gbrain git submodule — knowledge-graph sidecar (opt-in)
```

Four layers: **ingestion/catalog** (connectors → unified docs) · **memory** (Qdrant docs + `org_memory` evolving state + gbrain graph) · **reasoning** (LLM router) · **action** (native connectors + Composio).

## Capability status

| Capability | Endpoint | Status |
|---|---|---|
| Ask OSAI (RAG + propose/confirm actions) | `POST /ask`, `/ask/actions/{id}/confirm` | ✅ live |
| Semantic search | `POST /search` | ✅ live |
| Org knowledge graph | `GET /graph/entities`, `/graph/edges` | ✅ live |
| Eval harness | `GET /evals` | ✅ live (8/8) |
| Evolving memory | (in `/ask` + `/search`) | ✅ live |
| Composio tools (web search + connect apps) | `/integrations/composio/*` | ✅ live |
| gbrain knowledge graph | (opt-in via `OSAI_GBRAIN_HOME`) | ✅ wired |
| Live LLM answer text | — | ⚠️ needs OpenRouter credits or a billed Gemini key |

Without an LLM generation key, retrieval/citations/memory/Composio all work; only the final synthesized *answer text* falls back to a deterministic mock.

## Run the backend locally

**Prerequisites:** Docker (or [Colima](https://github.com/abiosoft/colima) — `brew install colima docker docker-compose && colima start`), [`uv`](https://docs.astral.sh/uv/) (`brew install uv`).

```bash
# 1. infra (Postgres, Qdrant, Redis)
docker compose up -d postgres redis qdrant      # or: docker-compose ...

# 2. backend
cd osai-backend
cp .env.example .env                            # then set keys you have (all optional)
uv sync
uv run alembic upgrade head
uv run python -m db.seed
uv run uvicorn api.main:app --reload --port 8000
```

API at `http://localhost:8000` (`/health`, `/docs`). Frontend expects this origin.

### Gotchas (learned the hard way)
- **Postgres port:** docker-compose maps Postgres to host **5433**. Running the backend on your host → set `OSAI_DATABASE_URL=...@localhost:5433/osai`. Inside Docker → 5432.
- **Embeddings need Gemini** (free tier works). Without it, a hash-embedding fallback is used (fine for dev).
- **`git submodule update --init`** after cloning, or `services/gbrain` is empty.

## Keys (all optional — set what you have in `osai-backend/.env`)

| Var | Enables |
|---|---|
| `OSAI_GEMINI_API_KEY` | Embeddings (free tier) + text-gen (needs billing) |
| `OSAI_OPENROUTER_API_KEY` | Text generation (needs account credits) |
| `OSAI_COMPOSIO_API_KEY` | 1000+ tool integrations |
| `OSAI_GBRAIN_HOME` | gbrain knowledge-graph sidecar |
| Connector tokens (Slack/Notion/Freshdesk/GDrive) | Real ingestion + actions |

## Tests

```bash
cd osai-backend
uv run ruff check .
uv run pytest          # live-key tests skip automatically when keys are unset
```

CI (`.github/workflows/ci.yml`) runs lint + tests on every backend PR against real Postgres/Qdrant/Redis.

## Deploy

The backend is a Docker image (`osai-backend/Dockerfile`) that migrates on start and serves on `:8000`. The full stack (API + worker + Postgres + Redis + Qdrant) runs via Compose with **persistent volumes**:

```bash
cp osai-backend/.env.example osai-backend/.env   # set keys (OSAI_LLM_API_KEY etc.)
docker compose up -d --build
docker compose exec api uv run python -m db.seed   # first run: seed demo data
```

**Hosted deployment (Render — free tier):** [`render.yaml`](render.yaml) provisions only free-eligible services — a Web service (API), free Postgres, and free Key Value (Redis). Qdrant runs on **Qdrant Cloud's free tier** (Render's private services and background workers require a paid plan, so they're left out; the demo runs fully synchronously in the API).

1. Create a free Qdrant cluster at [cloud.qdrant.io](https://cloud.qdrant.io) → copy its **URL** and **API key**.
2. Render → **New → Blueprint** → pick this repo (it reads `render.yaml`).
3. After it provisions, set the `sync: false` secrets on the `osai-api` service: `OSAI_QDRANT_URL`, `OSAI_QDRANT_API_KEY` (from step 1), `OSAI_GEMINI_API_KEY`, `OSAI_LLM_API_KEY` (Groq), `OSAI_COMPOSIO_API_KEY`, `OSAI_ALLOWED_ORIGINS` (your Vercel URL).
4. Migrations run on boot; seed once via the Render shell: `uv run python -m db.seed`.

`OSAI_DATABASE_URL`/`OSAI_REDIS_URL` are wired by the Blueprint; the app auto-converts Render's `postgresql://` URL to the psycopg driver. Note: free web services cold-start after inactivity, and free Postgres is time-limited — fine for a pilot, upgrade for production. Frontend (`osai-web`) stays on Vercel — point it at the API via `NEXT_PUBLIC_API_BASE_URL`.

**Async at scale (paid):** add a `type: worker` service (Celery) for background ingestion when you outgrow synchronous processing.

## Contributing (two-lane workflow)

Backend lives in `osai-backend/`, frontend in `osai-web/` — work in your lane, branch per task (`be/...` / `fe/...`), open a PR. See [`OSAI_PARALLEL_PLAN.md`](OSAI_PARALLEL_PLAN.md).
