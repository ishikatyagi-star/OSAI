# OSAI

AI-native operations layer for universities — a **company brain + reasoning + action** system. Connect your tools, ask anything, and let OSAI retrieve, remember, and take action.

> Start with the [deployment guide](docs/deploy.md), [API contract](docs/api-contract.md), and [contributor guide](CONTRIBUTING.md). Active feature work is tracked in the plans that remain in this repository.

## Architecture

```
osai-backend/   FastAPI · SQLAlchemy · Qdrant (RAG) · Gemini/OpenAI-compatible LLM · Celery
osai-web/       Next.js frontend (chat, graph inspector, eval dashboard, connectors)
services/gbrain optional Bun CLI submodule for the knowledge graph (not in Compose)
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
| gbrain knowledge graph | (opt-in via `OSAI_GBRAIN_HOME`) | ⚙️ source-wired; requires Bun + initialization |
| Live LLM answer text | — | ⚠️ needs `OSAI_LLM_API_KEY` (Groq by default) or Gemini generation access |

Local development can run without provider keys and uses deterministic fallbacks. Non-local deployments fail fast without a Gemini key because semantic embeddings are required.

## Run the backend locally

**Prerequisites:** Docker (or [Colima](https://github.com/abiosoft/colima) — `brew install colima docker docker-compose && colima start`), [`uv`](https://docs.astral.sh/uv/) (`brew install uv`).

```bash
# 1. infra (Postgres, Qdrant, Redis)
docker compose up -d postgres redis qdrant      # or: docker-compose ...

# 2. backend
cd osai-backend
cp .env.example .env                            # local defaults work; add provider keys as needed
uv sync
uv run alembic upgrade head
uv run python -m db.seed
uv run uvicorn api.main:app --reload --no-proxy-headers --port 8000
```

API at `http://localhost:8000` (`/health`, `/docs`). Frontend expects this origin.

### Gotchas (learned the hard way)
- **Postgres port:** docker-compose maps Postgres to host **5433**. Running the backend on your host → set `OSAI_DATABASE_URL=...@localhost:5433/osai`. Inside Docker → 5432.
- **Embeddings need Gemini** (free tier works). Without it, a hash-embedding fallback is used (fine for dev).
- **gbrain is optional and host-run.** If enabling it, initialize `services/gbrain` and its brain directory; the root Compose stack does not start it.

## Runtime configuration

Local development can use fallbacks. A non-local deployment requires a strong `OSAI_JWT_SECRET` and `OSAI_GEMINI_API_KEY`; production sign-in also needs the three Google OAuth variables documented in `osai-backend/.env.example`.

| Var | Enables |
|---|---|
| `OSAI_GEMINI_API_KEY` | Semantic embeddings (required outside local) + fallback text generation |
| `OSAI_LLM_API_KEY` | Text generation through `OSAI_LLM_BASE_URL` (Groq by default) |
| `OSAI_JWT_SECRET` | Session signing; required and validated outside local |
| `OSAI_COMPOSIO_API_KEY` | 1000+ tool integrations |
| `OSAI_GBRAIN_HOME` | Optional host-side gbrain CLI graph integration |
| Connector tokens (Slack/Notion/Freshdesk/GDrive) | Real ingestion + actions |

## Tests

```bash
cd osai-backend
uv run ruff check .
uv run pytest          # live-key tests skip automatically when keys are unset
```

CI (`.github/workflows/ci.yml`) runs lint + tests on every backend PR against real Postgres/Qdrant/Redis.

## Deploy

The backend image (`osai-backend/Dockerfile`) migrates on start for hosted deployments and serves on `:8000`. Compose uses a separate one-shot migration service before starting the API and worker; Postgres and Qdrant use persistent volumes.

```bash
cp osai-backend/.env.example osai-backend/.env   # set keys (OSAI_LLM_API_KEY etc.)
docker compose up -d --build
docker compose exec api uv run python -m db.seed   # first run: seed demo data
```

**Hosted deployment (Render):** [`render.yaml`](render.yaml) defines the API, a paid Starter Celery worker, and free Key Value (Redis). It intentionally does not deploy or wire the experimental Hermes sidecar: its shared-UID homes are namespaces, not a multi-tenant security boundary. It retains a legacy free Render Postgres declaration only to avoid destructive deletion during Blueprint sync; the API and worker use a dashboard-managed Supabase `OSAI_DATABASE_URL`. Qdrant runs on Qdrant Cloud. The worker consumes the automation `execute` queue and runs Celery beat for recurring automations. Composio ingestion still uses an API background task and is not yet hosted worker offload.

1. Create a free Qdrant cluster at [cloud.qdrant.io](https://cloud.qdrant.io) → copy its **URL** and **API key**.
2. Render → **New → Blueprint** → pick this repo (it reads `render.yaml`).
3. Fill every `sync: false` value required by the services you deploy. Set the shared database, Qdrant, Gemini, and JWT values on API/worker as declared in `render.yaml`; set `OSAI_ALLOWED_ORIGINS`, `OSAI_SQL_DSN_ENCRYPTION_KEYS`, and all three Google OAuth values on the API. Configure the generic LLM endpoint, Composio, and Slack only when those features are enabled. The SQL encryption key must be present before migration `0032` if SQL sources exist. Do not manually attach the experimental Hermes sidecar to this multi-tenant deployment.
4. Migrations run on boot; seed once via the Render shell: `uv run python -m db.seed`.

`OSAI_REDIS_URL` is wired by the Blueprint. `OSAI_DATABASE_URL` is a dashboard-managed Supabase secret and must be set on both API and worker; the app auto-converts `postgresql://` URLs to the psycopg driver. Do not point the services at the legacy Render database block. Frontend (`osai-web`) stays on Vercel — point it at the API via `NEXT_PUBLIC_API_BASE_URL`.

The Blueprint's worker command is `uv run celery -A workers.celery_app worker -B -Q execute --loglevel=info`. Keep it at one instance while beat runs in-process; split beat into a separate single-instance service before scaling workers horizontally.

## Contributing (two-lane workflow)

Backend lives in `osai-backend/`, frontend in `osai-web/` — work in your lane, branch per task (`be/...` / `fe/...`), and open a PR. See [CONTRIBUTING.md](CONTRIBUTING.md).
