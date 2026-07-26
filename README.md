# OSAI / Sheldon

**An AI-native operations layer for organizations — a company brain that retrieves, remembers, reasons, and acts.**

Connect your workspace tools (Google Drive, Gmail, Slack, Notion, read-only SQL), ask questions in natural language, and get grounded, cited answers — with proposed actions a human approves before anything is written back.

> **Naming:** the codebase and repo are `OSAI`; the shipped product is branded **Sheldon** (`osai-web` UI, page title "Sheldon - Operating System for Company Context"). The two names refer to the same system.

| | |
|---|---|
| Repo | `github.com/ishikatyagi-star/OSAI` |
| Backend | FastAPI + Celery (Python 3.12+), deployed on **Render** |
| Frontend | Next.js 16 / React 19, deployed on **Vercel** |
| Database | **Supabase** Postgres (dashboard-managed secret, *not* the legacy Render block) |
| Vectors | **Qdrant Cloud** (collection `osai_chunks`) |
| Queue / limiter | Render Key Value (Redis) |

---

## Table of contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [How an answer is produced](#how-an-answer-is-produced)
- [Capability status (as built)](#capability-status-as-built)
- [Repository map](#repository-map)
- [Data model](#data-model)
- [Auth, tenancy, and data governance](#auth-tenancy-and-data-governance)
- [Run it locally](#run-it-locally)
- [Configuration reference](#configuration-reference)
- [Tests and CI](#tests-and-ci)
- [Deploy](#deploy)
- [Known limitations](#known-limitations)
- [Documentation index](#documentation-index)
- [Contributing](#contributing)

---

## What it does

Four things, in order:

1. **Ingest** — pulls documents out of connected SaaS tools (via [Composio](https://composio.dev) OAuth, or native connector credentials), plus direct file uploads (txt/md/csv/log/pdf/docx). Content is chunked, embedded, and indexed into Qdrant; metadata and permissions land in Postgres.
2. **Remember** — three memory surfaces: the vector index (documents), `org_memory` (facts, decisions, resolutions, and playbooks that evolve as the org uses the system), and an optional gbrain wiki-graph mirror. "Remember that X" in Ask writes straight to `org_memory`.
3. **Reason** — retrieval-augmented answers through an OpenAI-compatible LLM (Groq by default), optionally routed through the **Hermes** sidecar for agentic multi-step work. Answers are **grounded-only**: if retrieval finds nothing, the system says so instead of guessing.
4. **Act** — the agent *proposes* connector actions (post to Slack, create a ticket, draft an email); a human confirms, and only then does it execute. Recurring work is expressed as **automations** with manual / hourly / daily / weekly cadences, external webhook triggers, and delivery to Slack or in-app notifications.

Around that core: an org knowledge graph, a workflow/action-item extractor, read-only SQL sources with an approval step, saved artifacts, a decisions log, team/department management with invites, an eval harness, and a dashboard.

## Architecture

```
osai-backend/          FastAPI · SQLAlchemy 2.0 · Alembic · Celery (+beat) · Qdrant · Redis
  api/routes/          27 routers - ask, search, integrations, automations, sql, team, ...
  agent/               orchestrator (the Ask pipeline), tools, delivery, hermes_client,
                       automation_runner, context
  memory/              embeddings, chunker, qdrant_store, retriever, org_memory,
                       supermemory_client, gbrain_client
  connectors/          composio_{tool,ingest,agent,live}, notion, slack, freshdesk,
                       google_drive, registry, sync_service, toolkit_map
  llm/                 gemini (Groq/Gemini router), ollama, policy (data-routing egress)
  workflows/           action-item extraction runner + enricher + prompts
  graph/               org graph providers (Postgres FK graph; gbrain provider seam)
  evals/               fixture harness + Hermes golden-dataset export
  workers/             celery_app, beat schedule, scheduler_health, tasks/
  db/                  models, repositories, session/auth guards, 35 Alembic migrations

osai-web/              Next.js 16 (App Router) · React 19 · Tailwind 4 · Radix
  app/                 ask, search, dashboard, integrations, automations, workflows,
                       graph, sql, team, decisions, notifications, artifacts, evals,
                       settings, onboarding, login, landing, demo, ...
  lib/                 api.ts (typed client), types.ts, demo-data.ts
  e2e/ tests/          Playwright specs + node:test unit tests

services/hermes-sidecar/  optional HTTP service wrapping the Hermes agent CLI
services/hermes/          vendored upstream (NousResearch/hermes-agent-self-evolution)
services/gbrain/          vendored upstream (garrytan/gbrain) - optional Bun CLI
```

Conceptually: **ingestion/catalog** → **memory** → **reasoning** → **action**, with the data-governance filter applied inside retrieval rather than bolted on afterwards.

## How an answer is produced

`POST /ask` → `agent/orchestrator.run_ask`:

1. **Memory shortcut** — "remember that ..." is stored in `org_memory` and returns immediately, never touching RAG.
2. **Retrieval** (`memory/retriever.py`) — org-memory keyword recall + Qdrant vector search (limit 8) → relevance floor → **re-validation of every hit against Postgres** (so a deleted or revoked document can never be served from a stale index) → per-requester permission and tier filter → department filter → relative cutoff.
3. **Grounding gate** — `grounded = enough_context or live_context`. No context and no live read → the honest "No relevant context found" and the model is never called.
4. **Optional live read / Composio function-calling agent** — fresh reads from connected apps. Both are **off by default**: they require an admin caller *and* an org data-routing policy that permits red-tier content to reach a cloud LLM.
5. **Synthesis** — the Hermes sidecar when configured and grounded, otherwise the cloud LLM; falls back to raw-retrieval text if synthesis fails.
6. **Action planning** — an LLM planner (or a keyword heuristic without a key) *proposes* actions; nothing executes until `POST /ask/actions/{id}/confirm`, which atomically claims the proposal so two concurrent confirms cannot both fire.
7. **Response** — answer, citations with confidence, `enough_context`, `via`, `model_route`.

Ask is idempotent for signed-in callers: a `request_id` is durably reserved in `ask_exchanges` before any model work; the same id with a different payload returns 409.

### Retrieval relevance floor

`OSAI_RETRIEVAL_MIN_SCORE` defaults to **the active embedding provider's recommended value** rather than a fixed number, because cosine scales differ sharply between providers — Jina v3 runs around 0.35, others default to 0.5. Setting it explicitly overrides the provider recommendation.

## Capability status (as built)

| Capability | Surface | Status |
|---|---|---|
| Ask (RAG + propose/confirm actions) | `POST /ask`, `/ask/actions/{id}/{confirm,dismiss}` | live |
| Semantic search | `POST /search` | live |
| Composio connectors (Notion, Google Drive, Slack, Gmail) | `/integrations/composio/*` | live - OAuth, ingest, reconnect, per-user connections |
| Direct document upload | `POST /documents/upload` | live - max 10 files, 15 MB each, 30 MB batch, isolated parser process |
| Automations | `/automations/*` incl. external `X-Trigger-Token` webhook | live for `manual`; recurring cadences gated on scheduler health |
| Org knowledge graph + access map | `/graph/entities`, `/graph/edges`, `/graph/access` | live |
| Read-only SQL sources | `/sql/*` | live, admin-only, encrypted DSNs |
| Workflows / action items | `/workflows/*` (incl. action-item approve/cancel) | live |
| Team, departments, invites | `/team/*` | live |
| Slack slash-command Ask | `POST /slack/ask/{token}` | live - HMAC-verified, fails closed |
| Evals | `GET /evals` | live |
| Hermes agentic execution | sidecar in `services/hermes-sidecar` | optional; configured in prod, silent RAG fallback on failure |
| gbrain knowledge graph | `OSAI_GBRAIN_HOME` | opt-in, host-run (needs Bun); not in Compose |
| Supermemory memory backbone | `OSAI_SUPERMEMORY_API_KEY` | optional; normal-tier content only unless self-hosted |
| Zoom webhook | `POST /webhooks/zoom` | intentionally dead (unconditional 404) |
| Queued ingest/execute Celery tasks | `workers/tasks/{ingest,execute}.py` | stubs - real ingest runs as an in-process FastAPI background task |

`GET /capabilities` reports what a given deployment can actually do (`environment`, `scheduler`, `automation_cadences`, `connectors`, `sql_sources`, `workflow_execution`, `semantic_embeddings`, `embedding_model`, `google_oauth`, `email_login`, `zoom_webhook`). **The frontend gates features on these flags** instead of assuming a fully provisioned stack.

### The demo workspace is read-only

`demo-org` is a public, read-only tenant. Every write and side-effect route — including `/ask` and `/search` — is guarded by `require_writable_org` and **403s for demo**. The web app catches that and renders **hardcoded fixture answers** from `lib/demo-data.ts`, fuzzy-matched to the question. This is intentional, but it means *demo Ask never calls a model*, and an unmatched question returns a confident-looking default fixture. Evaluate answer quality in a real workspace, never in demo.

## Repository map

| Path | What lives there |
|---|---|
| `osai-backend/` | The API, workers, and all data/retrieval logic. See its own [README](osai-backend/README.md) for rate-limit budgets. |
| `osai-web/` | Next.js frontend; also serves the deployed landing page (`public/osai.html` via `app/route.ts`). |
| `services/` | Hermes sidecar (first-party) plus vendored `hermes` and `gbrain` submodules. |
| `evals/`, `osai-backend/evals/` | Fixture-based eval harness and Hermes golden-dataset export. |
| `scripts/` | Production canary and deployment-config checks. |
| `docs/` | API contract, deploy guide, design system, and the most recent QA report. |
| `.github/workflows/` | `ci` (backend), `web-ci`, `e2e`, `hermes-sidecar-ci`, `automations-cron`, `keep-alive`, `production-canary`. |

## Data model

Authoritative source: `osai-backend/db/models.py`; migrations under `db/migrations/versions/` (35 revisions, head `20260723_0033`).

Core tables: `orgs`, `users`, `departments`, `invites`, `connectors`, `connector_accounts`, `sync_runs`, `source_documents`, `chunks`, `org_memory`, `threads`, `thread_turns`, `ask_exchanges`, `connector_actions`, `automations`, `automation_trigger_requests`, `workflow_runs`, `action_items`, `decisions`, `notifications`, `saved_artifacts`, `sql_sources`, `answer_feedback`, `audit_events`, `model_calls`, plus the single-use guards `oauth_state_uses` and `slack_request_uses`.

Invariants worth knowing:

- `users.email` is normalized and protected by a **functional unique index** — identity is DB-enforced.
- `sql_sources.dsn` has a CHECK requiring the `osai-fernet-v1:` prefix, so a plaintext DSN is rejected by the database itself.
- `ask_exchanges` is unique on `(org_id, user_id, request_id)`; `automation_trigger_requests` on `(automation_id, idempotency_key)`.
- Qdrant point ids are `uuid5(NAMESPACE_URL, "{org}:{chunk_id}")` — re-syncs are stable and orgs cannot collide.
- Ingest stores a SHA-256 `embedded_hash` per document, namespaced by embedding provider, so unchanged docs are not re-embedded and switching providers forces a clean re-embed.

## Auth, tenancy, and data governance

- **Sessions:** HS256 JWT in an httpOnly `osai_session` cookie (30-day expiry). `Authorization: Bearer` is also accepted and takes precedence. A `token_version` claim revokes every outstanding token for a user.
- **Tenancy:** the org comes from the **verified JWT only**. Any `org_id` in a request body is overwritten server-side. The `X-Org-Id` header is honored *only* for the literal `demo-org`.
- **Guard ladder:** `get_org_id` (read) → `require_writable_org` (write; rejects demo) → `require_admin`, which checks the **current DB role**, so a demotion takes effect immediately rather than at token expiry. A token whose principal no longer exists raises 401 rather than degrading to a see-all system context.
- **Read authorization lives inside retrieval.** Chunks are filtered by the requester's grants and data tier; person-scoped (`user:`) content is visible only to its named users — **even admins cannot read a teammate's private upload**.
- **Egress policy** (`llm/policy.py`): per-org data routing decides which tiers (normal / amber / red) may reach a cloud model. Red-to-cloud is **denied by default**, which is what keeps live connector reads off unless an admin deliberately widens it.
- **Rate limits:** Redis-backed, isolated per tenant/client/route, and **fail closed with 503** in production when Redis cannot enforce a budget. Budgets live in `api/ratelimit.py` (interactive AI 20/min, provider actions 10/min, ingestion 10/hour, and so on).
- **Sign-in:** Google OAuth with full OIDC verification (JWKS, audience, issuer, `email_verified`) and constant-time signed-cookie CSRF state. Password-less email login exists but is disabled outside local.

## Run it locally

**Prerequisites:** Docker (or [Colima](https://github.com/abiosoft/colima) — `brew install colima docker docker-compose && colima start`), [`uv`](https://docs.astral.sh/uv/), Node 20+ for the frontend.

```bash
git clone https://github.com/ishikatyagi-star/OSAI.git
cd OSAI
git submodule update --init --recursive
```

### Backend

```bash
docker compose up -d postgres redis qdrant      # or: docker-compose ...

cd osai-backend
cp .env.example .env                            # local defaults work; add provider keys as needed
uv sync
uv run alembic upgrade head
uv run python -m db.seed
uv run uvicorn api.main:app --reload --no-proxy-headers --port 8000
```

API at `http://localhost:8000` — `/health`, `/health/ready`, `/capabilities`, `/docs`.

### Frontend

```bash
cd osai-web
cp .env.example .env.local                      # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm install
npm run dev                                     # http://localhost:3000
```

### Gotchas (learned the hard way)

- **Postgres host port is 5433.** Compose maps `5433:5432`. Running the backend on the host means `OSAI_DATABASE_URL=...@localhost:5433/osai`; inside Docker it is 5432.
- **No embedding key means the hash-vector fallback**, which is keyword bucketing, not semantics. Fine for local; a non-local deployment **refuses to boot** in that state by design.
- **Colima stops when the Mac sleeps.** Restart with `colima start && docker-compose up -d postgres redis qdrant`. Postgres and Qdrant data persist, but re-index if the collection comes back empty.
- **gbrain is optional and host-run** (needs Bun). The root Compose stack does not start it.
- **Free-tier Render is 0.15 vCPU / 512 MB.** Ingest is deliberately capped (5 MB per Drive file, 25 MB media transcription, batched embedding with per-minute pacing) to survive it.

## Configuration reference

All settings are `OSAI_`-prefixed pydantic settings in `osai-backend/config.py`; local values come from `osai-backend/.env`. Boot **fails fast** in non-local environments when the JWT secret is weak or default, both schedulers are enabled at once, the Hermes URL is set without a token, no embedding provider key is present, or the rate-limit proxy configuration is inconsistent.

| Variable | Enables / effect |
|---|---|
| `OSAI_DATABASE_URL` | Postgres. `postgresql://` is auto-converted to the psycopg driver. |
| `OSAI_JWT_SECRET` | Session signing. Must be at least 32 chars and non-default outside local. |
| `OSAI_QDRANT_URL` / `OSAI_QDRANT_API_KEY` | Vector store; the API key is required for Qdrant Cloud. |
| `OSAI_REDIS_URL` | Rate limiter, Celery broker, scheduler heartbeat. |
| `OSAI_JINA_API_KEY` | **Preferred** embeddings (`jina-embeddings-v3`), token-aware batching and per-minute pacing. |
| `OSAI_VOYAGE_API_KEY` | Alternative embeddings (`voyage-3.5-lite`). |
| `OSAI_GEMINI_API_KEY` | Embeddings (`gemini-embedding-001`) and fallback text generation. |
| `OSAI_LLM_API_KEY` / `_BASE_URL` / `_MODEL` | Text generation via any OpenAI-compatible endpoint (Groq + `llama-3.3-70b-versatile` by default). |
| `OSAI_COMPOSIO_API_KEY` | Connectors, catalog, OAuth, live reads. Absent means Integrations is empty. |
| `OSAI_COMPOSIO_AGENT_ENABLED` | Function-calling connector agent (default **false**). |
| `OSAI_COMPOSIO_PER_USER_CONNECTIONS` | Per-user OAuth connections and owner-scoped documents (default **false**). |
| `OSAI_GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | Production sign-in. |
| `OSAI_HERMES_SIDECAR_URL` / `_TOKEN` | Agentic execution through the Hermes sidecar; set both or neither. |
| `OSAI_SLACK_SIGNING_SECRET` / `OSAI_SLACK_BOT_TOKEN` | Slack Ask and delivery. A missing signing secret makes `/slack/ask` 503. |
| `OSAI_SQL_DSN_ENCRYPTION_KEYS` | Fernet keys for SQL source DSNs. Must exist before migration `0032` if SQL sources exist. |
| `OSAI_SUPERMEMORY_API_KEY` / `_URL` | Optional memory backbone. |
| `OSAI_GBRAIN_HOME` | Optional host-side gbrain graph mirror. |
| `OSAI_RETRIEVAL_MIN_SCORE` | Overrides the provider-recommended relevance floor. |
| `OSAI_ALLOWED_ORIGINS`, `OSAI_PUBLIC_BASE_URL`, `OSAI_FRONTEND_URL` | CORS and OAuth callback wiring. Without a public base URL, Composio auto-ingest after OAuth will not fire. |
| `OSAI_AUTOMATIONS_BEAT_ENABLED` / `_CRON_ENABLED` / `_CRON_TOKEN` | Recurring automations; exactly one scheduling mode may be enabled. |
| `OSAI_SENTRY_DSN` | Error reporting (inert when unset). |

## Tests and CI

```bash
cd osai-backend
uv run ruff check .
uv run pytest              # ~560 tests across 90 files; live-key tests skip when keys are unset
```

```bash
cd osai-web
npm run typecheck
npm test                   # node:test unit tests
npm run test:e2e           # Playwright, including axe accessibility checks
```

Coverage is weighted heavily toward security and tenancy invariants: auth isolation, demo read-only, department scope, ACLs on graph/enricher/retrieval, egress and data-routing fail-closed behavior, approver binding, action-confirmation fail-closed, idempotency, per-user Composio connections, embedding guards, and rate-limit budgets.

CI runs backend lint and tests against real Postgres/Qdrant/Redis service containers, plus web CI, Playwright e2e, sidecar CI, and a scheduled production canary.

### Frontend conventions (CI-enforced)

- No em dashes in `osai-web` source.
- Demo-mode writes need explicit copy explaining the read-only behavior.
- Tests assert against source text, so copy changes must update both.

## Deploy

The backend image (`osai-backend/Dockerfile`) runs migrations on start and serves on `:8000`. Compose uses a one-shot migration service before starting the API and worker; Postgres and Qdrant use persistent volumes.

```bash
docker compose up -d --build
docker compose exec api uv run python -m db.seed   # first run only
```

**Hosted (Render Blueprint, [`render.yaml`](render.yaml)):** an API web service (free), a Starter Celery worker running `-B -Q execute`, and free Key Value (Redis).

1. Create a Qdrant Cloud cluster and copy its URL and API key.
2. Render → **New → Blueprint** → select this repo.
3. Fill every `sync: false` value. Set database, Qdrant, embedding, and JWT values on both API and worker; set `OSAI_ALLOWED_ORIGINS`, `OSAI_SQL_DSN_ENCRYPTION_KEYS`, and the three Google OAuth values on the API.
4. Migrations run on boot; seed once from the Render shell with `uv run python -m db.seed`.
5. The frontend stays on Vercel — point it at the API with `NEXT_PUBLIC_API_BASE_URL`.

Deployment facts that bite:

- **`OSAI_DATABASE_URL` must stay a dashboard-managed Supabase secret.** `render.yaml` keeps a legacy free Render Postgres block only so a Blueprint sync does not destructively delete it. If a sync ever re-wires `fromDatabase`, the API points at the expired free database and crash-loops on boot.
- **Keep the worker at one instance** while beat runs in-process (`-B`). Split beat into its own single-instance service before scaling workers horizontally.
- **Do not attach the Hermes sidecar to the multi-tenant deployment.** Its per-tenant `HERMES_HOME` directories are namespaces under one OS UID, not a security boundary.
- The `osai-worker` / `osai-beat` services that predate the current blueprint are orphaned and fail every deploy; they are harmless to the API and web.

## Known limitations

Behavior that surprises people, and work that is known to be outstanding:

- **Demo Ask returns fixtures, not model output** (see above). This is the most likely explanation for any "hallucination" reported from a demo session.
- **Live connector reads and the Composio agent are off by default** — they need an admin caller *and* an org data-routing policy that has been widened to allow red-tier content to reach a cloud model. In a normal workspace, questions about connected apps are answered from previously-synced data only.
- **Failure paths are quiet.** Several grounding and synthesis fallbacks degrade silently: a Hermes failure logs a warning and falls back to RAG, and a vector-store outage is hard to distinguish from an empty index. A degraded answer carries no signal that it degraded. Improving this observability is tracked work.
- **`model_route` can misreport the engine** after a silent Hermes fallback — it is derived from configured keys, not the path actually taken.
- **Document counts can overstate what Ask can cite.** Filename-only documents are removed from the vector index but kept in Postgres, so "N indexed" exceeds N retrievable.
- **Automation delivery is not idempotent across retries** — a run that delivers and then crashes before recording can re-deliver on the next tick.
- **Recurring cadences depend on a fresh beat heartbeat.** When `scheduler=false`, non-manual cadences are refused at create/update time.
- **Authorization consistency work is outstanding on a few org-metadata read surfaces.** Roster and org-structure reads are available to any member of a workspace rather than admins only, which is deliberate in some places and unreviewed in others. Document content itself is always filtered per requester.
- **Native Notion `execute_action` always skips**, so an Ask-proposed Notion page routed to the native connector reports a failed action every time.
- **Some in-process state assumes a single API instance.** Ingest de-duplication and the fast-path proposal cache are per-process; horizontal scaling needs a shared lock first.
- **Dead schema:** `chunks` rows are written but never read by retrieval; `audit_events` has writers but no reader API; `model_calls` has neither writer nor reader.
- **Frontend list GETs swallow errors into empty defaults**, so a broken backend can render as an empty-but-healthy workspace unless the caller opts into `strict`.

## Documentation index

| Document | What it covers |
|---|---|
| [`docs/api-contract.md`](docs/api-contract.md) | The backend/frontend interface. |
| [`docs/deploy.md`](docs/deploy.md) | Deployment specifics. |
| [`docs/design-system.md`](docs/design-system.md) | Frontend design tokens and patterns. |
| [`docs/qa-report-2026-07-22.md`](docs/qa-report-2026-07-22.md) | Most recent QA pass. |
| [`PRODUCTION_READINESS_ACTION_PLAN.md`](PRODUCTION_READINESS_ACTION_PLAN.md) | The master production scope. |
| [`AGENTIC_AUTOMATIONS_PLAN.md`](AGENTIC_AUTOMATIONS_PLAN.md) | Fixing the dead-end automation UX. |
| [`PROMPTQL_GAP_PLAN.md`](PROMPTQL_GAP_PLAN.md) | Retrieval and memory gap closure. |
| [`MADVERSE_PILOT_READINESS.md`](MADVERSE_PILOT_READINESS.md) | Pilot-specific readiness. |

Additional internal records — the as-built forensic trace, the security audit, the smoke-test checklist, and the Supabase rebuild plan — are kept out of this public repository. Ask the maintainers if you need them.

## Contributing

Backend lives in `osai-backend/`, frontend in `osai-web/`. Work in your lane, branch per task (`be/...` / `fe/...`), and open a focused PR. See [CONTRIBUTING.md](CONTRIBUTING.md).
