# OSAI Build Roadmap

_From a working demo slice → a "company brain + reasoning + action" product for university operations._

Owners: **Ishika = Backend**, **Co-founder = Frontend**. Goal: ship a credible university pilot **ASAP**, reusing external repos/services aggressively (Composio, gbrain, etc.) — **no building from scratch**.

---

## 0. Reality check — what already works today

Contrary to "it does nothing," the backend is a real end-to-end vertical slice:

| Layer | Status | Where |
|---|---|---|
| Connectors (Slack, Notion, GDrive, Freshdesk) | Real: `sync`, `search`, `execute_action` | `connectors/` |
| RAG memory (Qdrant + embeddings + retriever) | Real | `memory/` |
| LLM (Gemini + Ollama fallback, router) | Real | `llm/` |
| Workflow: transcript → action items | Real (Gemini, RAG context) | `workflows/runner.py` |
| Action execution: approve item → push to connector | Real (Freshdesk/Slack/Notion) | `api/routes/workflow_actions.py` |
| DB (orgs, users, docs, chunks, runs, items, audit, model_calls, data tiers, permissions) | Real | `db/models.py` |
| Async workers (Celery: ingest/extract/execute) | Real | `workers/` |
| Next.js frontend | Scaffold only, not wired to live API | `osai-web/` |

**Conclusion:** keep OSAI as the thin harness. We are *enriching*, not replacing.

---

## Target architecture (4 layers)

1. **Ingestion + catalog** — connectors normalize to a unified schema; every item registered in a typed catalog (type, source, lineage, permissions).
2. **Memory (3 sub-layers)** —
   - Knowledge base: Qdrant (docs) **+ gbrain** (typed graph).
   - Agent/org memory: evolving state (preferences, past resolutions, decisions).
   - Context timeline: per-session prompts/tool-calls (UltraContext).
3. **Reasoning** — Gemini router reads memory, plans tool sequences, emits structured actions.
4. **Agent + action** — workflows/workers execute plans via native connectors **+ Composio**, log back into memory.

---

## Phased plan

Each phase lists **owner**, **deliverable (demoable)**, and **depends on**. Phases 0–1 are the critical path to a compelling demo; 2–6 deepen it.

### Phase 0 — Light up the existing slice (THIS WEEK)
> Before adding anything, prove what we have runs with real keys. This de-risks everything and tells us what's actually broken.

- **Backend (Ishika):**
  - Stand up `docker-compose` (Postgres, Qdrant, Redis), run Alembic migrations + seed.
  - Create `.env` with real **Gemini** key + **one** real connector token (recommend Slack or Notion).
  - Run a real sync → confirm docs land in Postgres + Qdrant.
  - Run transcript → action-item workflow → approve → confirm push to connector.
- **Frontend (Co-founder):**
  - Wire dashboard pages to the live API (replace mocks).
  - Clean "run workflow" + "review/approve action items" screens.
- **Deliverable:** a recorded end-to-end demo of current capability on real data.

### Phase 1 — "Ask OSAI" general agent ⭐ (demo centerpiece)
> The single highest-leverage feature. Reuses everything in Phase 0.

- **Backend (Ishika):** new `/ask` (agent) endpoint that retrieves via the existing retriever, builds a **tool-enabled** Gemini prompt (function-calling), can invoke existing connector actions, returns **answer + citations + actions taken**.
- **Frontend (Co-founder):** "Ask OSAI" chat UI — streaming, source citations, action-confirmation cards.
- **Deliverable:** "Ask OSAI a question about your org → cited answer → optionally take an action."

### Phase 2 — Tool breadth via Composio
- **Backend (Ishika):** spike Composio auth; build `connectors/composio_tool.py` adapter exposing Composio actions through the same tool interface the agent already uses. Native connectors for core vertical; Composio for the long tail (Gmail, Calendar, Jira, HubSpot…).
- **Deliverable:** agent takes actions in tools we never hand-coded.

### Phase 3 — Separate memory from retrieval
- **Backend (Ishika):**
  - New Alembic migration: typed `Entity` (Person/Org/Course/Department/Ticket/Document/Meeting), `Source`, `Edge`.
  - `agent_state` / `org_memory` table for evolving state (preferences, past resolutions, decisions).
  - Mark Qdrant as **document retrieval only**; write outcomes to memory on workflow completion; fetch relevant memories into context on new tasks.
- **Deliverable:** "OSAI remembers how we handled a similar ticket last week and reuses it."

### Phase 4 — Knowledge brain (gbrain)
- **Backend (Ishika):** **spike first** — fork + stand up gbrain (per-org git repo + pgvector). On sync, generate/update markdown pages in the org brain repo. Extend retriever to query Qdrant **+** gbrain and merge/rerank.
- **Frontend (Co-founder):** "Org graph inspector" page (entities + relationships).
- **Deliverable:** "Ask OSAI" answers cite both vector docs **and** graph edges.

### Phase 5 — Context versioning (UltraContext) _(optional / later)_
- **Backend (Ishika):** store per-session context; build prompts from it; check out old versions to reproduce agent behavior for debugging/eval.

### Phase 6 — Evals + self-improvement (Hermes) _(ongoing)_
- **Backend (Ishika):** extend `model_calls` logging to full input/output/error capture; build a fixture library of university scenarios + success criteria; plug the most important skill (e.g. ticket triage) into Hermes/GEPA prompt evolution.

---

## Division of labor (summary)

| | Ishika (Backend) | Co-founder (Frontend) |
|---|---|---|
| Phase 0 | Run stack, real keys, one connector, verify slice | Wire dashboard to live API, workflow + approval screens |
| Phase 1 | `/ask` agent endpoint (RAG + tool-calling) | "Ask OSAI" chat UI w/ citations |
| Phase 2 | Composio adapter | Connector/tool management UI |
| Phase 3 | Typed schema + memory tables | (light) memory surfacing in UI |
| Phase 4 | gbrain integration + hybrid retrieval | Org graph inspector page |
| Phase 5–6 | UltraContext, evals, Hermes | Eval/debug views |

---

## Risks / decisions to confirm

- **External repo validation:** gbrain / UltraContext / agentmemory / Hermes are recent/early. Each gets a short **spike** to confirm it actually works and is forkable *before* we commit a phase to it. If a repo is immature, we build a minimal in-house equivalent (e.g. a small `org_memory` table instead of full agentmemory).
- **Composio cost:** commercial; confirm pricing/free tier before Phase 2.
- **Hosting:** the Vercel site is just the landing page. The backend (FastAPI + Postgres + Qdrant + Redis + Celery) needs a real host (Render/Railway/Fly/a VM). Decide before pilot.
- **Single agent first:** start with one powerful "Ask OSAI" agent; add planner/executor/critic multi-agent patterns only if needed.
