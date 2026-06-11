# OSAI — Comprehensive Execution Plan

**Audience:** any engineer *or* AI coding agent (including a local / open-source model) executing this build.
**Goal:** turn OSAI from a single working demo slice into a "company brain + reasoning + action" product for university operations, **as fast as possible**, by **reusing public repositories and third-party services instead of building from scratch**.

> Companion docs: [`OSAI_BUILD_ROADMAP.md`](OSAI_BUILD_ROADMAP.md) is the short executive summary. **This file is the authoritative, detailed plan.** If they ever disagree, follow this file.

---

## 0. How to use this document (rules for the executor)

If you are an AI agent or junior engineer executing tasks here, obey these rules:

1. **Do tasks in order.** Each task has an ID like `P1-T2`. Do not start a task until its **Prerequisites** are met.
2. **Stop at every "✅ Acceptance check."** Run the check. If it fails, fix it before moving on. Never mark a task done without passing its check.
3. **Never invent file paths, env var names, API routes, or library names.** If something is not written here, search the codebase first (`grep`, read the file). If still unknown, **ask a human** — do not guess.
4. **Match existing code style.** Read the neighbouring file before writing a new one. OSAI backend is Python 3.12, FastAPI, SQLAlchemy 2.0, `uv` for deps, `ruff` for lint.
5. **The polyglot rule (critical):** gbrain, agentmemory, and UltraContext are **Node/TypeScript** services. OSAI backend is **Python**. **You do NOT import them into Python.** You run each as a **separate sidecar service / MCP server** and call it over **HTTP or MCP** from Python. Never try to `pip install` a TypeScript project.
6. **Secrets** live only in `osai-backend/.env` (which is git-ignored). Never hardcode keys. Never commit `.env`.
7. After each task, run `uv run ruff check .` and `uv run pytest` in `osai-backend/`. Both must pass.

---

## 1. Current state (what already works — do NOT rebuild)

The backend is a real end-to-end slice. Confirmed by reading the code:

| Capability | Where | Status |
|---|---|---|
| Connectors: Slack, Notion, Google Drive, Freshdesk — `sync` / `search` / `execute_action` | `osai-backend/connectors/` | Working |
| RAG memory: chunking, embeddings, Qdrant store, retriever | `osai-backend/memory/` | Working |
| LLM: Gemini client + router + Ollama local fallback | `osai-backend/llm/` | Working |
| Workflow: meeting transcript → action items (with RAG context) | `osai-backend/workflows/runner.py` | Working |
| Action execution: approve item → push to Freshdesk/Slack/Notion | `osai-backend/api/routes/workflow_actions.py` | Working |
| DB schema: orgs, users, connectors, sync_runs, source_documents, chunks, workflow_runs, action_items, connector_actions, audit_events, model_calls; data tiers + permissions | `osai-backend/db/models.py` | Working |
| Async workers (Celery): ingest / extract / execute | `osai-backend/workers/` | Working |
| Next.js frontend (dashboard, inbox, workflows, etc.) | `osai-web/` | **Scaffold — not wired to live API** |

**What's missing vs. the vision:** a general "ask anything" agent; broad integrations; a typed knowledge graph; separated memory layers (knowledge vs. evolving state vs. session context); evals/self-improvement. The phases below add exactly these.

---

## 2. External repositories & services we will use

**Strategy:** reuse, don't rebuild. Each row is something other people already built. Integration pattern column tells you *how OSAI (Python) talks to it*.

| # | Name | Repo / URL | License | Runtime | What it gives OSAI | Integration pattern |
|---|---|---|---|---|---|---|
| 1 | **Composio** | https://github.com/ComposioHQ/composio · https://composio.dev | OSS SDK + commercial API (generous free tier) | Python SDK (3.10+) **native** | 1000+ tool integrations (Gmail, Calendar, Jira, HubSpot, Slack, Notion…) with auth handled for you | **Python SDK — import directly.** This is the one external piece that lives *inside* the backend. |
| 2 | **gbrain** | https://github.com/garrytan/gbrain | MIT | TypeScript / Bun + Postgres | Markdown-first **typed knowledge graph** (people, orgs, meetings, edges like `works_at`, `attended`) with zero-LLM extraction + hybrid search; exposes **74 tools over MCP** | **Sidecar service.** Run gbrain; OSAI calls its HTTP/MCP API per org. |
| 3 | **agentmemory** | https://github.com/rohitg00/agentmemory | Apache-2.0 | TypeScript (npx), local storage | Persistent **agent/user memory** — captures decisions/outcomes, injects relevant memory on new tasks; MCP server | **Sidecar MCP server.** OSAI logs to it and queries it over MCP/HTTP. (Or build the minimal in-house `org_memory` table — see P3.) |
| 4 | **UltraContext** | https://github.com/ultracontext/ultracontext | OSS | Node ≥ 22 | **Git-style versioned context** per session (create/get/append/update/delete); branch/diff/revert agent context | **Sidecar service.** Store per-session context; build prompts from it. (Optional / later — P5.) |
| 5 | **Hermes Agent Self-Evolution** | https://github.com/NousResearch/hermes-agent-self-evolution | OSS | Python (DSPy + GEPA) | Offline **eval + automatic prompt/skill optimization**, ~$ a few dollars per run, no GPU | Run as an offline job against logged session data (P6). |
| 6 | **AIOS** | https://github.com/agiresearch/AIOS | OSS | Python | Reference design for an "agent OS kernel" (scheduling, lifecycle) | **Reference only — do not fork.** Use to sanity-check our abstractions. |

**Deliberately NOT used now:** agentmemory + UltraContext (covered in-house to keep the stack lean), OpenHuman (GPL-3 — would force our code open, avoid), Context.dev (external web context — only if we later need sales/marketing signals), Sentra (enterprise data-security — revisit when selling to large enterprises).

---

## 2.5 How each repo is physically pulled & run (decided)

Two integration styles. **Composio installs like any dependency. gbrain/Hermes are cloned.** We never copy a TypeScript project's source into Python.

| Repo | How we get it | Lives where | How it runs | Status |
|---|---|---|---|---|
| **Composio** | `uv add composio` (a Python package) | inside `osai-backend` deps | in-process, in the backend | install at P2 — **no clone** |
| **gbrain** | `git submodule` (already added) | `services/gbrain/` in this repo | its own container in the compose stack; `gbrain serve --http`, called over HTTP/MCP | ✅ **cloned now** |
| **Hermes** | `git clone` when we reach P6 | `services/hermes/` (submodule) | offline job, run occasionally | clone later (P6) |

**Why a submodule (not copy-paste):** our repo stores only a *pointer* to gbrain's commit, so we stay clean and can pull their updates — but it still lives "in one repo" for hosting. **One catch your co-founder must know:** after cloning the OSAI repo, they must run:
```bash
git submodule update --init --recursive   # otherwise services/gbrain is an empty folder
```

**Deployment:** a single top-level `docker-compose.yml` will define every service — OSAI API, worker, Postgres, Qdrant, Redis, **and gbrain** — so the whole product is `docker compose up` to **one** host. Building the gbrain container from `services/gbrain` is part of Phase 4.

---

## 3. Locked architectural decisions

These are decided. Do not re-litigate during execution.

- **D1 — OSAI stays the thin Python harness.** We enrich it; we never fork AIOS/OpenHuman wholesale.
- **D2 — Composio is the primary integration/action layer.** The existing hand-rolled connectors (Slack/Notion/GDrive/Freshdesk) **keep working** for ingestion, but **all new tools/actions go through Composio.** We do not hand-write new connectors. Retiring the native connectors entirely is allowed *later* once Composio coverage is proven (see open decision O1).
- **D3 — One repo, one deploy stack, minimal sidecars.** Everything lives in the OSAI monorepo and deploys as **one Docker Compose stack to one host**. We use the *fewest possible* extra services:
  - **Composio** — a Python **library** (`uv add composio`); runs *inside* OSAI, **no extra service, no clone**.
  - **gbrain** — the **one** Node sidecar we adopt. Vendored into the repo as a **git submodule at `services/gbrain`** (MIT). Runs as a container in the same compose stack; Python calls it over HTTP/MCP.
  - **agentmemory** and **UltraContext** — **NOT used.** Their jobs are covered in-house (a small Postgres `org_memory` table) to avoid extra services. Revisit only if proven insufficient.
  - **Hermes** — cloned **later** (Phase 6); it's an offline job, not a hosted service.
- **D4 — One agent first.** Build a single powerful "Ask OSAI" agent. Add multi-agent (planner/executor/critic) only if a concrete need appears.
- **D5 — Memory is three distinct layers** (per Needle's "vector DBs aren't memory"): (a) **knowledge base** = Qdrant (documents) **+ gbrain** (typed entity graph), (b) **agent/org memory** = evolving state in the in-house `org_memory` table (preferences, past resolutions), (c) **session context** = kept simple in-app for now. Qdrant is explicitly **document retrieval only**. The typed knowledge graph is **delegated to gbrain** — we do **not** hand-build Entity/Edge tables.

---

## 4. Environment & setup reference

### 4.1 Prerequisites (install once)
- Docker + Docker Compose
- `uv` (Python package manager) — backend
- Node ≥ 22 + `bun` — only for the gbrain service (`services/gbrain`); runs via Docker in the compose stack
- `git submodule update --init --recursive` after cloning (pulls `services/gbrain`)
- Git, and a Composio account (free tier) → API key from https://app.composio.dev

### 4.2 The port gotcha (read this — it breaks people)
`docker-compose.yml` maps Postgres to host port **5433** (`5433:5432`). But `osai-backend/.env.example` and `alembic.ini` use **5432**.
- If you run the backend **inside Docker** (`docker compose up`): use host `postgres`, port **5432**.
- If you run the backend **on your host machine** against the Docker Postgres: use `localhost`, port **5433**.
Pick one mode and set `OSAI_DATABASE_URL` consistently. Most "can't connect to DB" errors are this.

### 4.3 Backend run commands (from `osai-backend/`, uv-based)
```bash
uv sync                                  # install deps
uv run pytest                            # run tests
uv run alembic upgrade head              # apply migrations
uv run python -m db.seed                 # seed demo org/data
uv run uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### 4.4 Complete `.env` reference (`osai-backend/.env`)
Start from `.env.example`. Variables added by this plan are marked **NEW**.
```bash
OSAI_ENV=local
OSAI_DATABASE_URL=postgresql+psycopg://osai:osai@localhost:5433/osai   # see 4.2
OSAI_QDRANT_URL=http://localhost:6333
OSAI_QDRANT_COLLECTION=osai_chunks
OSAI_EMBEDDING_DIMENSION=768
OSAI_DEFAULT_ORG_ID=demo-org
OSAI_ALLOWED_ORIGINS=http://localhost:3000
OSAI_REDIS_URL=redis://localhost:6379/0

# LLM
OSAI_GEMINI_API_KEY=                      # required for real search/workflows/agent

# Native connectors (kept for ingestion)
OSAI_NOTION_API_TOKEN=
OSAI_NOTION_ROOT_PAGE_ID=
OSAI_SLACK_BOT_TOKEN=
OSAI_FRESHDESK_DOMAIN=yourcompany.freshdesk.com
OSAI_FRESHDESK_API_KEY=
OSAI_GOOGLE_SERVICE_ACCOUNT_JSON=path/to/service_account.json
OSAI_GOOGLE_DRIVE_FOLDER_ID=

# NEW — Composio (P2) — Python library, just needs the key
OSAI_COMPOSIO_API_KEY=
# NEW — gbrain service in the compose stack (P4)
OSAI_GBRAIN_URL=http://gbrain:4000
```

---

## 5. Repository layout after this plan

New/changed paths the executor will create (✚ = new):
```
osai-backend/
  connectors/
    composio_tool.py        ✚ P2  Composio adapter (Python SDK)
  agent/                    ✚ P1  the "Ask OSAI" agent
    __init__.py
    orchestrator.py         ✚ P1  retrieve → tool-calling loop → answer+citations
    tools.py                ✚ P1  tool registry (native connectors + Composio)
  memory/
    org_memory.py           ✚ P3  evolving agent/org state (in-house) OR agentmemory client
    gbrain_client.py        ✚ P4  HTTP client to gbrain sidecar
    hybrid_retriever.py     ✚ P4  merge Qdrant + gbrain results
  api/routes/
    agent.py                ✚ P1  POST /ask endpoint
    graph.py                ✚ P4  GET /graph endpoints for the inspector UI
  db/migrations/versions/
    <ts>_entities_edges.py  ✚ P3  Entity / Source / Edge tables
    <ts>_org_memory.py      ✚ P3  org_memory table
  evals/                    ✚ P6
    fixtures/               ✚ P6  university scenarios + expected outputs
    run_evals.py            ✚ P6
infra/
  sidecars/
    docker-compose.sidecars.yml ✚ P4 gbrain + agentmemory + ultracontext
osai-web/                   (co-founder) chat UI, graph inspector, live API wiring
```

---

## 6. The phases

Legend — **Owner:** B = Ishika (backend), F = co-founder (frontend). **Critical path = P0 → P1.**

---

### PHASE 0 — Light up the existing slice  *(target: 2–4 days)*
*Prove what exists runs on real data before adding anything.*

**P0-T1 (B) — Boot the stack.**
Steps: install Docker; from repo root run `docker compose up -d postgres redis qdrant`; in `osai-backend/` copy `.env.example`→`.env`, set `OSAI_DATABASE_URL` per §4.2; `uv sync`; `uv run alembic upgrade head`; `uv run python -m db.seed`; `uv run uvicorn api.main:app --reload`.
✅ **Acceptance:** `GET http://localhost:8000/health` returns 200; `uv run pytest` passes.

**P0-T2 (B) — Real LLM.**
Get a Gemini API key, set `OSAI_GEMINI_API_KEY`. Restart API.
✅ **Acceptance:** `POST /workflows` with a sample meeting transcript returns extracted action items with `model_route` starting `gemini:` (not `heuristic-fallback`).

**P0-T3 (B) — One real connector end-to-end.** Recommend **Slack** or **Notion** (simplest tokens).
Set the token; trigger a sync (via the integrations route / sync_runs); confirm rows in `source_documents` + vectors in Qdrant.
✅ **Acceptance:** a sync run shows `documents_indexed > 0`; `POST /search` returns a real chunk from that source.

**P0-T4 (B) — Full loop: extract → approve → push.**
Run the transcript workflow with `destination` = the connected connector; approve an action item via `POST /workflows/{run_id}/action-items/{item_id}/approve`.
✅ **Acceptance:** approval response has `status: executed` and an `external_url`; the item actually appears in Slack/Notion/Freshdesk.

**P0-T5 (F) — Wire the frontend to the live API.**
Replace mock data in `osai-web/` with real calls to `http://localhost:8000`. Make the **workflow run** + **review/approve action items** screens functional.
✅ **Acceptance:** you can run a workflow and approve an item entirely from the UI.

**📦 Phase 0 deliverable:** a recorded end-to-end demo on real data. This tells us exactly what's broken before we build more.

---

### PHASE 1 — "Ask OSAI" general agent  ⭐ *(target: 1 week)*
*The demo centerpiece. Reuses everything from Phase 0. Highest leverage.*

**P1-T1 (B) — Tool registry.** Create `agent/tools.py`: a function that returns the available tools for an org as JSON schemas Gemini can call. Start by wrapping the **existing** connector `execute_action` methods (post Slack message, create Notion page, create Freshdesk ticket) and the existing `search`/retriever as a `search_knowledge` tool.
✅ **Acceptance:** unit test lists ≥ 3 tools with valid JSON schemas.

**P1-T2 (B) — Orchestrator.** Create `agent/orchestrator.py`: given a question + org_id → (1) call `search_knowledge` (retriever), (2) build a Gemini prompt with retrieved context + tool definitions, (3) run a **tool-calling loop** (Gemini requests a tool → we execute it → feed result back) until Gemini returns a final answer, (4) return `{answer, citations[], actions_taken[]}`. Reuse `llm/gemini.py`; add a `generate_with_tools` helper if needed. Log each step to `audit_events` + `model_calls`.
✅ **Acceptance:** asking a question whose answer is in an ingested doc returns the right answer **with a citation** pointing to that document.

**P1-T3 (B) — `/ask` endpoint.** Create `api/routes/agent.py` with `POST /ask {org_id, question}` → calls the orchestrator → returns the structured response. Register the router in `api/main.py`.
✅ **Acceptance:** `curl POST /ask` returns answer + citations JSON; an action-type question (e.g. "open a ticket for X") triggers a real connector action and reports it in `actions_taken`.

**P1-T4 (F) — "Ask OSAI" chat UI.** Build a chat page in `osai-web/` hitting `/ask`: message list, streaming/loading state, **citation chips** (click → source), and **action confirmation cards** ("OSAI wants to create a Freshdesk ticket — Approve?").
✅ **Acceptance:** a non-technical person can ask a question and get a cited answer in the browser.

**📦 Phase 1 deliverable:** "Ask OSAI anything about your org → cited answer → optionally take an action." This is the pilot demo.

---

### PHASE 2 — Tool breadth via Composio  *(target: 3–5 days)*
*Stop hand-writing integrations. Composio covers the long tail.*

**P2-T1 (B) — Spike.** Create a Composio account (free tier), set `OSAI_COMPOSIO_API_KEY`. In a scratch script, authenticate one app (e.g. Gmail or Google Calendar) and execute one action via the **Composio Python SDK**. Confirm it works and note the free-tier limits.
✅ **Acceptance:** a real action (e.g. send a test email / create a calendar event) succeeds via Composio from Python.

**P2-T2 (B) — Adapter.** Create `connectors/composio_tool.py`: a thin wrapper that (a) lists available Composio actions for an org, (b) converts each to the **same tool-schema format** `agent/tools.py` already uses, (c) executes a chosen action. Add Composio tools into the agent's tool registry so the orchestrator can call them transparently.
✅ **Acceptance:** the orchestrator can call at least one Composio action (e.g. `create_calendar_event`) end-to-end via `/ask`, with no native connector written.

**P2-T3 (B) — Coverage list.** Enable the toolkits a university pilot needs (Gmail, Google Calendar, Slack, Jira/ticketing, HubSpot if relevant). Document which are native vs. Composio.
✅ **Acceptance:** `GET /integrations` (or equivalent) lists Composio-backed tools alongside native connectors.

**📦 Phase 2 deliverable:** OSAI takes actions in tools we never hand-coded.

---

### PHASE 3 — Add evolving agent memory  *(target: 3–5 days)*
*The typed knowledge graph is delegated to gbrain (Phase 4), so Phase 3 is just the in-house evolving-state layer. This is smaller than before.*

> **Changed:** we do **not** hand-build `entities`/`sources`/`edges` tables — gbrain owns the typed graph (Phase 4). Phase 3 only adds the small `org_memory` table.

**P3-T1 (B) — `org_memory`.** Migration + model for evolving state: `org_memory` (id, org_id, user_id?, kind ∈ {preference, decision, resolution, playbook}, content, embedding ref?, created_at, source_run_id). Create `memory/org_memory.py` with `record_memory(...)` and `fetch_relevant(org_id, query)`.
> **Why in-house, not agentmemory:** a single Postgres table needs zero extra service and keeps the deploy to one stack (decision D3). agentmemory stays off the table unless recall quality proves insufficient.
✅ **Acceptance:** completing a workflow writes a `resolution` memory; `fetch_relevant` returns it for a similar later query.

**P3-T2 (B) — Wire memory into the agent.** In the orchestrator: before answering, call `fetch_relevant` and add a "Memory" section to the prompt; after a workflow/action, call `record_memory`. Make Qdrant explicitly **document-retrieval only** (no agent state in vectors).
✅ **Acceptance:** demo effect — "OSAI remembers how we handled a similar ticket last week and reuses that resolution."

**📦 Phase 3 deliverable:** OSAI distinguishes knowledge (docs) from memory (evolving state) and is visibly "stateful."

---

### PHASE 4 — Knowledge brain (gbrain)  *(target: 2–3 weeks)*

**P4-T1 (B) — Stand up gbrain.** Already vendored at `services/gbrain` (submodule). Add it to the top-level `docker-compose.yml` as a service (build from `services/gbrain`, run `gbrain serve --http`). Set `OSAI_GBRAIN_URL` to the in-stack URL. Read `services/gbrain/AGENTS.md` + `llms.txt` for the exact serve command and API.
✅ **Acceptance:** `docker compose up` brings gbrain up; you can create a markdown page in gbrain and query it back via its HTTP/MCP API.

**P4-T2 (B) — Ingestion → brain.** After each connector/Composio sync, generate/update markdown pages in the org's brain (tickets, docs, recurring entities). Create `memory/gbrain_client.py` (Python HTTP/MCP client to the gbrain service).
✅ **Acceptance:** syncing a Notion page creates/updates a corresponding gbrain markdown page + graph entities.

**P4-T3 (B) — Hybrid retrieval.** Create `memory/hybrid_retriever.py`: query **both** Qdrant and gbrain, merge (top-k each) and rerank by relevance. Swap the agent's `search_knowledge` tool to use it.
✅ **Acceptance:** an `/ask` answer cites **both** a vector doc and a gbrain graph edge/page.

**P4-T4 (F) — Org graph inspector.** Page in `osai-web/` calling new `api/routes/graph.py` (`GET /graph/entities`, `GET /graph/edges`) to visualize entities + relationships for the pilot university.
✅ **Acceptance:** the inspector shows real people/departments/tickets and how they connect.

**📦 Phase 4 deliverable:** a true "company brain" — answers grounded in a typed knowledge graph + documents, with a visual inspector.

---

### PHASE 5 — Context versioning (UltraContext)  *(optional / later, 1 week)*

**P5-T1 (B)** Run UltraContext (Node ≥ 22) as a sidecar; set `OSAI_ULTRACONTEXT_URL`.
**P5-T2 (B)** For each `/ask` session/workflow, store the context (prompt, retrieved memory, tool calls, messages) in UltraContext and **build the next prompt from it** instead of ad-hoc assembly.
**P5-T3 (B)** Add a debug path: check out an older context version to reproduce an agent run exactly.
✅ **Acceptance:** you can diff two versions of a session's context and replay an old one.
**📦 Deliverable:** reproducible, versioned agent context for debugging and eval.

---

### PHASE 6 — Evals + self-improvement (Hermes)  *(ongoing)*

**P6-T1 (B) — Logging.** Extend `model_calls` (and audit) to capture full input/output/error for every agent + workflow run.
**P6-T2 (B) — Fixtures.** Create `evals/fixtures/` with ~10–20 real university scenarios (ticket triage, "who owns X", routing) + expected outputs + success criteria. Add `evals/run_evals.py` to score the current system.
✅ **Acceptance:** `uv run python evals/run_evals.py` prints a pass-rate over the fixture set.
**P6-T3 (B) — Hermes on one skill.** Pick the highest-value skill (e.g. ticket triage). Clone https://github.com/NousResearch/hermes-agent-self-evolution; feed it the skill's prompt + the fixture/eval set; let DSPy+GEPA search better prompts; promote the winner into production.
✅ **Acceptance:** measurable eval-score improvement on that skill after a Hermes run.
**📦 Deliverable:** OSAI's most important skill auto-improves from real data.

---

## 7. Ownership summary

| Phase | Ishika (Backend) | Co-founder (Frontend) |
|---|---|---|
| P0 | stack up, real keys, 1 connector, verify full loop | wire UI to live API; workflow + approval screens |
| P1 ⭐ | tool registry + orchestrator + `/ask` | "Ask OSAI" chat UI (citations, action cards) |
| P2 | Composio adapter + coverage | tools/integrations management UI |
| P3 | entity/edge schema + `org_memory` + wire into agent | surface "what OSAI remembers" in UI |
| P4 | gbrain sidecar + ingestion + hybrid retrieval | org graph inspector page |
| P5 | UltraContext sidecar + context build/replay | session/debug viewer |
| P6 | logging + eval harness + Hermes | eval dashboards |

---

## 8. Open decisions for the founders (answer before the relevant phase)

- **O1 (before P2 finishes):** Once Composio coverage is proven, do we **retire** the hand-rolled connectors (less code to maintain) or **keep** them (no per-action Composio cost, full control)? Recommendation: keep native for the 1–2 core ingestion sources, Composio for everything else.
- **O2 (before P3):** in-house `org_memory` table vs. adopting the **agentmemory** sidecar. Recommendation: in-house first; adopt agentmemory only if recall quality is insufficient.
- **O3 (before pilot):** **hosting.** The Vercel site is just the landing page. The backend (FastAPI + Postgres + Qdrant + Redis + Celery + sidecars) needs a real host — Render / Railway / Fly.io / a VM. Decide and provision.
- **O4 (ongoing):** Composio free-tier limits — monitor usage; know the paid threshold before the pilot scales.

---

## 9. Source

Component choices and rationale come from the founder's `OSAI-NEXT-STEPS.pdf` brief. Repo URLs and licenses verified via web search, June 2026:
gbrain (MIT) · agentmemory (Apache-2.0) · UltraContext · Composio · Hermes Self-Evolution · AIOS.
