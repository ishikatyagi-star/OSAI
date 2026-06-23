# OSAI — Architecture & Codebase Guide

Everything you need to understand the system end to end: what each part does, why
it exists, what's wired up, the tokens/keys and their purposes, and what's planned
next. Written so you can answer any question about the codebase confidently.

---

## 1. What OSAI is

OSAI is a **company brain**: it ingests an organization's scattered context
(Notion, Google Drive, Slack, …), indexes it into a searchable knowledge base,
and lets people **ask questions** (cited answers), **see decisions/tasks**, and
**run actions/automations** — all governed by **per-org isolation**, **roles**,
and **data-sensitivity tiers**.

### High-level architecture

```
Browser ──HTTPS──► Next.js frontend (Vercel)
                        │  Authorization: Bearer <JWT>
                        ▼
                   FastAPI backend (Render, Docker)
        ┌───────────────┼───────────────────────────┐
        ▼               ▼                            ▼
   Postgres         Qdrant Cloud               External services
 (system of record) (vector search)   Google OAuth · Composio · Groq LLM ·
                                       Gemini embeddings · (Redis/Celery)
```

- **Frontend:** Next.js (App Router, TypeScript) on Vercel — `osai-web/`.
- **Backend:** FastAPI (Python 3.12) on Render via Docker — `osai-backend/`.
- **Postgres:** relational system of record (orgs, users, documents, chunks, …).
- **Qdrant Cloud:** vector store for semantic search over chunk embeddings.
- **Redis:** provisioned for Celery (background worker is **not** running on the
  free tier yet — see Future plans).

---

## 2. Tech stack & why

| Layer | Tool | Why |
|---|---|---|
| Backend framework | **FastAPI** | async, typed, dependency-injection (used for auth/org scoping) |
| ORM | **SQLAlchemy 2.0** | typed models; multi-tenant queries filtered by `org_id` |
| Migrations | **Alembic** | versioned schema; runs on Render boot |
| Auth tokens | **PyJWT** | verify Google `id_token` (RS256/JWKS) + sign our session JWT (HS256) |
| HTTP client | **httpx** | Google token exchange, Composio, LLM, Whisper, Hermes calls |
| Vector DB client | **qdrant-client** | semantic retrieval (`query_points`) |
| LLM | **Groq** (OpenAI-compatible) | free, fast `llama-3.3-70b-versatile` for answers/planning |
| Embeddings | **Google Gemini** | `gemini-embedding-001` (768-dim) for chunk vectors |
| Transcription | **Groq Whisper** | `whisper-large-v3` for Drive audio/video (free, reuses LLM key) |
| Integrations | **Composio** | OAuth + tool execution for 1000+ apps (Notion/Drive/Slack/…) |
| Background jobs | **Celery + Redis** | async ingestion / scheduled automations (worker not deployed yet) |
| Frontend | **Next.js + React + TypeScript** | App Router pages; `lucide-react` icons |
| Lint/format | **ruff** (py), **tsc** (ts) | enforced locally + CI |

---

## 3. Tokens, keys & secrets — what each is for

Set as environment variables (Render for backend, Vercel for frontend). Values are
never committed; `.env` is git-ignored. Purposes:

| Env var | Purpose |
|---|---|
| `OSAI_JWT_SECRET` | **Signs our session JWTs** (HS256). The single most security-critical secret — until set, a dev default signs tokens (forgeable). |
| `OSAI_GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | **Google sign-in** (OAuth 2.0/OIDC). Identify users; exchange the auth code for an `id_token`. |
| `OSAI_GOOGLE_OAUTH_REDIRECT_URI` | Where Google returns the user after consent (`…/auth/google/callback`). |
| `OSAI_LLM_API_KEY` (+ `_BASE_URL`, `_MODEL`) | **Groq** key — LLM answer synthesis/planning **and** Whisper transcription (reused). |
| `OSAI_GEMINI_API_KEY` | **Embeddings** (chunk vectors for Qdrant). Text-gen via Gemini is a fallback only. |
| `OSAI_QDRANT_URL` / `_API_KEY` | **Vector DB** (Qdrant Cloud) connection. |
| `OSAI_COMPOSIO_API_KEY` | **Integrations** — Composio OAuth connect + tool execution (Drive/Notion/Slack/Gmail/…). |
| `OSAI_TRANSCRIBE_*` | Optional override for transcription provider/model (defaults to Groq Whisper). |
| `OSAI_FRONTEND_URL` / `OSAI_ALLOWED_ORIGINS` | Post-login redirect target + CORS allow-list. |
| `OSAI_PUBLIC_BASE_URL` | This API's public URL (used in the Composio auto-ingest callback). |
| `OSAI_HERMES_SIDECAR_URL` | Optional — route automations through a per-user Hermes sidecar (off by default). |
| `OSAI_REDIS_URL` / `OSAI_DATABASE_URL` | Redis (Celery) + Postgres connection strings (set by the Render blueprint). |
| Frontend `NEXT_PUBLIC_API_BASE_URL` | Tells the web app where the backend is. |

**Token *types* in play:**
- **Google `id_token`** (RS256, signed by Google) — proves identity; verified against Google's JWKS.
- **OSAI session JWT** (HS256, signed by us with `OSAI_JWT_SECRET`) — carries `sub` (user id), `org_id`, `role`, `email`, `exp`; sent as `Authorization: Bearer`.
- **OAuth access tokens for connectors** — held by **Composio**, not us (no token-sharing); we call Composio with our API key + the user/org id.

---

## 4. Authentication & authorization

**Sign-in (`api/routes/auth.py`):**
- `GET /auth/config` — tells the frontend if Google is enabled.
- `GET /auth/google/start` — redirect to Google consent (scope `openid email profile`, CSRF `state` cookie).
- `GET /auth/google/callback` — exchange the code (`_exchange_code`), **verify the `id_token`** via Google JWKS (`_verify_id_token`: RS256, audience + issuer + `email_verified` checks), find/create the user, issue our JWT (`_issue_token`), redirect to the web `/auth/callback#…` with the token in the URL fragment (kept out of logs).
- `POST /auth/login` — dev-only email lookup (no password). Not for production.

**Session JWT:** `_issue_token(user)` encodes `{sub, org_id, role, email, iat, exp}` with HS256. Expiry `OSAI_JWT_EXPIRY_HOURS` (default 720h).

**Authorization (`db/session.py`):**
- `get_org_id` — resolves the caller's org **from the verified Bearer JWT**, never a client header (the only header-trusted case is the public `demo-org`). This is what stops org A reading org B's data.
- `get_claims` / `get_optional_claims` — full claims (required / nullable).
- `require_admin` — gates admin-only writes (team invites/departments/member updates, `/orgs/{id}/reset-content`).
- Every org-scoped route depends on `get_org_id`; `/ask`, `/search`, `/workflows`(create) override any body `org_id` with the authenticated one.

**Multi-tenant join:** on Google sign-in, if a **pending invite** matches the verified email, the user joins that org with the invited role/department; otherwise a new org is provisioned. Invites are email-based, auto-accepted on sign-in (no email infra) — admin shares `/login?invite=<email>`.

---

## 5. Backend — module & route map

`osai-backend/`

### `api/routes/` (HTTP surface, all registered in `api/main.py`)
| Route file | Endpoints | Purpose |
|---|---|---|
| `health.py` | `GET /health` | liveness |
| `auth.py` | `/auth/*` | Google OIDC sign-in + JWT issuance (§4) |
| `orgs.py` | `POST /orgs`, `POST /orgs/{id}/reset-content` | provision org; admin-only wipe of ingested content (keeps connections) |
| `team.py` | `/team/members,departments,invites` | members list, role/department updates, departments CRUD, invites (admin-gated writes) |
| `agent.py` | `POST /ask`, `/ask/actions/{id}/confirm` | RAG answer + propose/execute connector actions (org from JWT) |
| `search.py` | `POST /search` | retrieval-only (merged into Ask in the UI; route kept) |
| `integrations.py` | `/integrations…` | list connectors (overlays live Composio connection state), sync, healthcheck, tier-rules CRUD, `{key}/documents` |
| `composio.py` | `/integrations/composio/*` | list toolkits, OAuth connect, callback (auto-ingest), connections |
| `sync_runs.py` | `GET /sync-runs` | ingestion history |
| `workflows.py` + `workflow_actions.py` | `/workflows…` | meeting action-item extraction + approve/execute |
| `automations.py` | `/automations…` | NL scheduled tasks; "Run now" executes via the agent (Hermes seam) |
| `dashboard.py` | `GET /dashboard/metrics` | live aggregates for the Analytics page |
| `graph.py` | `/graph/entities,edges,access` | org graph + the access map (who-can-access-what) |
| `evals.py` | `GET /evals` | answer-quality eval run |
| `settings.py` | `/settings/data-routing` | per-tier connector/LLM policy |
| `webhooks.py` | `/webhooks/zoom` | Zoom recording webhook (→ transcription worker) |

### Core modules
- **`db/`** — `models.py` (tables, §6), `session.py` (engine + auth dependencies), `repositories.py` (all data access: provisioning, integrations, tier rules, automations, reset, retrieval helpers), `migrations/` (Alembic).
- **`agent/`** — `orchestrator.py` (`run_ask`: RAG → answer → plan actions → confirm/execute), `hermes_client.py` (optional per-user Hermes sidecar seam, injects permission-scoped context).
- **`memory/`** — `retriever.py` (`retrieve_answer`: embed → Qdrant search → **permission filter `_visible`** → synthesize), `qdrant_store.py` (vector upsert/search/`delete_org`), `embeddings.py`, `chunker.py`, `org_memory.py` (facts/decisions/playbooks distinct from the doc KB).
- **`connectors/`** — `registry.py` (native connectors), `notion/slack/freshdesk/google_drive.py` (native sync; **no demo fallback in prod**), `sync_service.py` (sync + apply tier rules), `composio_tool.py` (Composio API client), `composio_ingest.py` (pull connected-app docs → KB; Whisper transcription for media), `toolkit_map.py` (Composio slug ↔ native key).
- **`workflows/`** — Gemini action-item extraction (`runner.py`, prompts).
- **`workers/`** — Celery tasks (`tasks/ingest.py` download+transcribe, `tasks/extract.py`). Worker not deployed on free tier.
- **`graph/provider.py`** — builds the entity graph and the access map from Postgres.
- **`evals/`** — fixture-based answer-quality harness; `hermes_export.py` exports a golden dataset.
- **`llm/router.py`** — provider-neutral LLM routing (Groq/OpenRouter/Gemini/…).

---

## 6. Data model (Postgres tables)

`orgs`, `users` (role + `permissions` JSON + `department_id`), `departments`,
`invites` (email/role/department/status), `connectors` (catalog), `connector_accounts`
(per-org connection: `auth_state`, `tier_rules` JSON), `sync_runs`, `source_documents`
(`data_tier`, `permissions`), `chunks` (`data_tier`, `permissions`), `workflow_runs`,
`action_items`, `connector_actions`, `automations` (NL tasks), `audit_events`,
`model_calls`, `org_memory`.

**Tenancy:** almost every table has `org_id`; queries filter by it. **Governance:**
`data_tier` (normal/amber/red) + `permissions` on documents/chunks drive what each
user can retrieve (`_visible`).

---

## 7. Integrations — how they work

- **Two paths:** *native* connectors (their own creds, e.g. a Drive service account) and *Composio* (OAuth per user, the primary path).
- **Connect:** UI → `POST /integrations/composio/connect/{toolkit}` → Composio returns an OAuth `redirect_url` → user authorizes → Composio callback → OSAI auto-ingests. After auth the user lands back on `/integrations?connected=1`.
- **Slug mapping** (`toolkit_map.py`): Composio `googledrive` ↔ native `google_drive`, etc., so one app = one card. `/integrations` overlays active Composio connections onto the native card.
- **Sync:** "Sync now" → if an active Composio connection exists, ingest via Composio (`ingest_composio_toolkit`), else the native connector. Ingestion writes `source_documents` + `chunks` (+ Qdrant vectors). Implemented fetchers: **Notion, Google Drive, Slack** (others connect but don't ingest yet).
- **Scopes:** OAuth scopes are managed by Composio's auth config per toolkit; OSAI requests `openid email profile` only for *sign-in* (separate from connector scopes).
- **Per-info tiers:** `connector_accounts.tier_rules` (pattern→tier); applied on ingest (`apply_tier_rules`) to set each doc's `data_tier`. Editable in the Manage drawer (per-file dropdown + folder/keyword rules).
- **Media transcription:** `_transcribe_media` downloads audio/video via Composio and transcribes with Groq `whisper-large-v3` (≤25MB; falls back to filename).

---

## 8. Agent, Automations & Hermes

- **Ask OSAI (`run_ask`):** retrieve permitted context → synthesize a cited answer (Groq) → propose connector actions → user confirms → execute via Composio. Permission-aware (`_visible`).
- **Automations:** NL task + cadence; **Run now** executes the prompt through the agent and stores the result. Recurring execution needs the Celery worker (not deployed) — Run now works today. Executor is a **seam**.
- **Hermes (off by default):** the seam (`agent/hermes_client.py` + `services/hermes-sidecar/`) lets a **per-user** Hermes agent run the task instead. OSAI injects the user's permission-scoped context, calls the sidecar (`hermes -z`) with `user_id`+permissions, isolated per-user `HERMES_HOME`. Enabled only by setting `OSAI_HERMES_SIDECAR_URL` after validating the sidecar (`services/hermes-sidecar/DEPLOY.md`). The forked `services/hermes` (hermes-agent-self-evolution) is a **prompt optimizer**, not the runtime.

---

## 9. Frontend — page & component map

`osai-web/` (Next.js App Router). Sidebar IA grouped Workspace / Manage / Configure.

| Route | Purpose |
|---|---|
| `/login` | Google sign-in + (gated) demo; invite banner |
| `/auth/callback` | stores the JWT from the OAuth redirect, routes onward |
| `/onboarding` | integrations-first, one connector at a time, each Connect/Skip |
| `/dashboard` | home overview (gated demo content) |
| `/dashboards` | **Analytics** — live metrics from `/dashboard/metrics` |
| `/ask` | Ask OSAI chat (cited answers, action cards) |
| `/inbox` | Context Inbox |
| `/decisions` | Decision Log (absorbed Team Board: "My"/"OSAI-identified" filters) |
| `/graph` | Org Graph **access map**, grouped by department |
| `/team` | Members / Departments / Invites |
| `/workflows`, `/workflows/[id]` | action-item workflows |
| `/automations` | NL automations (create / Run now) |
| `/integrations` | tabbed Connectors + Data Routing; ConnectorManager drawer |
| `/sync-runs` | ingestion history |
| `/settings`, `/settings/advanced` | settings hub + Evals; reset-workspace danger zone |
| `/search` → `/ask`, `/board` → `/decisions`, `/evals` → `/settings/advanced` | redirects (merged surfaces) |

**Key libs:** `lib/api.ts` (all backend calls; injects `Authorization: Bearer`, handles 401 → re-login), `lib/demo.ts` (`isDemo()` gates sample data so real workspaces are clean), `components/auth-wrapper.tsx` (route guard), `components/sidebar.tsx` (nav), `components/integrations/connector-manager.tsx` (Manage drawer: health, synced files, tiers).

---

## 10. Deployment

- **Backend:** Render Docker web service (`render.yaml` blueprint) + Postgres + Redis; Qdrant Cloud. Migrations run on boot. Secrets in the service's Environment tab.
- **Frontend:** Vercel, auto-deploys `main`. `NEXT_PUBLIC_API_BASE_URL` points at the Render API.
- **CI:** `.github/workflows/ci.yml` runs ruff + pytest (with Postgres/Qdrant/Redis service containers).
- **Landing page:** large single-file bundle at `osai-web/public/osai.html`, served by `app/route.ts`; marked `linguist-generated` so GitHub language stats reflect real code.

---

## 11. Versions / models / tags

- LLM: Groq **`llama-3.3-70b-versatile`** (OpenAI-compatible base `api.groq.com/openai/v1`).
- Embeddings: Gemini **`gemini-embedding-001`**, **768-dim**, Qdrant collection `osai_chunks`.
- Transcription: **`whisper-large-v3`** (Groq).
- Auth: Google **OAuth 2.0 / OIDC**; session **JWT HS256**; id_token verify **RS256** via Google JWKS.
- Python **3.12**, FastAPI, SQLAlchemy **2.0**, Alembic; Next.js App Router + TypeScript.

---

## 12. Known limitations & future plans

- **Celery worker not deployed** → recurring automations + async Zoom transcription don't auto-run yet (Run now / sync-on-connect work).
- **Hermes** is wired but unproven end-to-end → keep on the in-house agent until the sidecar passes its validation gate; then per-user Hermes with permission-scoped context.
- **Composio ingestion** implemented for Notion/Drive/Slack only; others connect but don't ingest.
- **Media >25MB** isn't transcribed (Whisper limit) → chunked transcription is future work.
- **Decisions/Inbox** are partly frontend-only (no full backend persistence yet).
- **`/auth/login`** (email lookup, no password) is dev-only; production sign-in is Google.
- **gbrain / UltraContext / Hermes-self-evolution** are reference/optional sidecars for richer memory + answer self-improvement (P4–P6), not in the live path.
