# Agentic Automations — Implementation Plan

**Goal:** Fix the automation-creation experience so that (1) the agent knows which
connectors the org/user has connected and asks for access instead of claiming it
has none, (2) creating an automation is a back-and-forth conversation that the
agent finishes by creating the automation itself once everything is clear,
(3) automations can be edited after creation, and (4) the agent never talks
about "CLI sessions", "cron jobs", or "Telegram delivery" — capabilities OSAI
does not expose.

**Origin (user-reported bug):** A user asked for "a daily summary of any new
connector I add and any new information that connector brings." The Hermes
sidecar replied as if it were a standalone CLI agent: it said it had no access
to connectors, asked clarifying questions the user could never answer (the
result was stored in `last_result`, a dead-end log with no reply mechanism),
and no usable automation was configured.

**Audience:** This plan is written to be implemented step by step without
additional design decisions. Each phase is independently shippable in order.
Read the referenced files before editing them and follow the existing code
style (module docstrings, comment density, error-handling patterns).

**Repo layout reminders:**
- Backend: `osai-backend/` (FastAPI + SQLAlchemy + Alembic). Routes in
  `api/routes/`, agent in `agent/`, connectors in `connectors/`, DB in `db/`.
- Frontend: `osai-web/` (Next.js app router). Automations UI:
  `osai-web/app/automations/page.tsx`.
- Existing propose→confirm action loop: `agent/orchestrator.py`
  (`_record`, `confirm_action`, `_PROPOSED`, `save_proposed_action`). **Reuse
  this loop for automation creation — do not invent a second confirmation
  mechanism.**

---

## Phase 1 — Connector awareness (backend)

The agent must know what is connected before it answers anything about
connectors.

### 1.1 Build a connector-context helper

New file: `osai-backend/agent/context.py`

```python
async def connector_context(org_id: str) -> str
```

- Gather **Composio connections** via the same client used by
  `GET /integrations/composio/connections` (`api/routes/composio.py:97` —
  read that handler and call the same underlying client method, not the HTTP
  route).
- Gather **native registered connectors** from
  `connectors.registry.connector_registry` (see how `agent/tools.py`
  `available_action_tools()` probes it), including each connector's
  `capabilities`.
- Return a short plain-text block, e.g.:

```
Connected data sources for this workspace:
- googledrive (Composio, connected 2026-07-01) — documents are synced into OSAI's knowledge base
- slack (native connector; capabilities: execute)
No other connectors are connected. Users can connect more from the Integrations page.
```

- Must never raise: wrap the whole body in try/except and return `""` on
  failure (same best-effort pattern as `_permitted_context` in
  `agent/hermes_client.py:29`).

### 1.2 Inject an environment preamble into every Hermes call

Edit `osai-backend/agent/hermes_client.py`, function `run_via_hermes`.

The root cause of the bad answer is that Hermes believes it is a
single-operator CLI agent. Prepend a system-style preamble to the `augmented`
prompt (before the permitted-context block):

```
You are OSAI, an internal AI assistant embedded in a web product.
Environment facts (do not contradict these):
- You are NOT in a CLI or terminal session. The user talks to you in a web chat.
- Automation results are shown on the user's Automations dashboard. Do not offer
  cron jobs, Telegram, email, or other delivery channels.
- OSAI automations run on a cadence of: manual, hourly, daily, or weekly.
- You DO have access to the workspace's connected data sources, listed below.
- If the user asks about a data source that is not connected, tell them to
  connect it from the Integrations page — never say you fundamentally lack
  connector access.

{connector_context(org_id)}
```

Add a parameter `extra_context: str = ""` to `run_via_hermes` rather than
hardcoding, and build the preamble in the callers' shared path — a small
helper `automation_preamble(org_id)` in `agent/context.py` is fine. Keep the
existing permitted-context injection unchanged after the preamble.

### 1.3 Inject the same context into the in-house path

In `agent/orchestrator.py` `run_ask`, the in-house answer comes from
`retrieve_answer` (RAG). Connector questions ("what's connected?", "summarize
new info from my connectors") aren't answerable from document RAG. Append the
connector-context block to the answer-synthesis context: read
`memory/retriever.py` first; if threading context in is invasive, the minimal
correct change is to include `connector_context` in the Hermes preamble (1.2)
and in the automation-run path (Phase 4) only, and leave plain RAG alone.
State in a code comment which option was taken.

### 1.4 Tests

`osai-backend/tests/` — follow existing test style (check `ls tests/`).
- `connector_context` returns "" when Composio unavailable (monkeypatch client).
- `run_via_hermes` payload includes the preamble (httpx mock, assert on
  `prompt` content: contains "NOT in a CLI", contains connector list).

---

## Phase 2 — Automation model upgrades + edit endpoint (backend)

### 2.1 Model changes

`osai-backend/db/models.py`, class `Automation` (line ~198). Add:

```python
status: Mapped[str] = mapped_column(String, default="active")  # draft|active|paused
updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)
```

Semantics: `draft` = created by the agent but still being clarified;
`active` = runs on cadence; `paused` = kept but not scheduled. `enabled`
stays for backward compat; treat `enabled=False` as `paused` when serializing.

### 2.2 Migration

New Alembic revision in `osai-backend/db/migrations/versions/`, modeled on
`20260617_0005_automations.py` (read it for the naming/format conventions,
and set `down_revision` to the **current head** — run
`alembic heads` or read the latest version file to find it). Adds the two
columns with server defaults (`'active'`, `now()`).

### 2.3 Repository + route

`db/repositories.py`: add

```python
def update_automation(session, org_id, automation_id, *, name=None, prompt=None,
                      cadence=None, enabled=None, status=None) -> Automation | None
```

Only set fields that are not None; return None if the row doesn't exist or
belongs to another org (same guard shape as `delete_automation`).

`api/routes/automations.py`:
- `class AutomationUpdate(BaseModel)` — all fields optional
  (`name`, `prompt`, `cadence`, `enabled`, `status`).
- `@router.patch("/{automation_id}")` — validate `cadence in VALID_CADENCES`
  and `status in ("draft", "active", "paused")` when provided; 404 on missing;
  return `_serialize(a)`.
- Extend `_serialize` with `status` and `updated_at`.
- `AutomationCreate` gains optional `status: str = "active"`.

### 2.4 Tests

- PATCH updates cadence/prompt; 404 for wrong org (two-org fixture — reuse the
  cross-tenant test pattern that exists for other routes).
- PATCH with invalid cadence → 400.

---

## Phase 3 — Conversational, agent-driven automation creation (backend)

The flow the user asked for: they describe the automation in chat → the agent
asks clarifying questions **in the same chat** → once clear, the agent
proposes creating the automation → one confirm click creates it. Reuse the
existing propose→confirm loop end to end.

### 3.1 New agent tools

`osai-backend/agent/tools.py` — add to `_ACTION_TOOLS`-style exposure, but
note these are **internal** tools (no connector behind them), so add a second
registry dict `_INTERNAL_TOOLS` with the same spec shape and merge it into
`tool_specs()` / `available_action_tools()` output:

- `create_automation` — params: `name` (string, required), `prompt` (string,
  required — the finalized, fully-specified instruction the agent composed
  from the conversation, NOT the user's raw message), `cadence` (enum
  manual|hourly|daily|weekly, required).
  Description: "Create a recurring OSAI automation once the user's intent is
  fully clear. Ask clarifying questions first if the goal, data sources, or
  cadence are ambiguous."
- `update_automation` — params: `automation_id` (required), plus optional
  `name`/`prompt`/`cadence`/`status`.
- `list_automations` — no params. Lets the agent answer "what automations do
  I have?" and find ids for updates.

### 3.2 Execution in the confirm path

`agent/orchestrator.py`:
- In `_plan_actions` / `_llm_plan`, internal tools flow through `_record` with
  `provider="internal"`.
- In `confirm_action`, before the `provider == "composio"` branch, add
  `provider == "internal"` → new `_execute_internal(action_id, proposed)`:
  - `create_automation` → call `db.repositories.create_automation` inside
    `SessionLocal()` (same session pattern as `_remember_resolution`),
    with the acting `user_id` from the descriptor. Return
    `ConfirmActionResult(status="executed", message=f"Automation '{name}' created — see the Automations page.")`.
  - `update_automation` / `list_automations` analogous. `list_automations`
    should NOT require confirmation — in `_record`, set
    `requires_confirmation=False` for read-only internal tools and execute
    them inline in `run_ask` (follow how the answer/actions are threaded;
    simplest correct version: skip proposing `list_automations` as an action
    and instead always include a one-line automations summary in the
    context when the question mentions "automation").
- Store `user_id` in the proposed-action descriptor (add the field in
  `_record` and thread it from `run_ask`'s `user_id` param — check
  `api/routes/agent.py` already passes it).

### 3.3 Planner prompt

In `_llm_plan`'s prompt, add one instruction line:

```
If the request is to set up a recurring task/automation but details are
ambiguous (which sources, what cadence, what output), return NO actions —
the answer should ask the clarifying question instead. Only propose
create_automation when the goal, sources, and cadence are all explicit in
the conversation.
```

Also extend `_heuristic_plan`: if the question contains "every day",
"daily", "automation", "remind", "every week" AND names a cadence AND a
concrete task, propose `create_automation` with `cadence` inferred; otherwise
propose nothing (the fallback answer will ask for details).

### 3.4 Multi-turn context

`AskRequest` already carries `history` (`api/schemas/agent.py:30`). Verify the
history reaches the planner and the Hermes prompt:
- In `run_via_hermes`, include the last ~10 history messages above the task
  (format: `User: …` / `Assistant: …` lines) so clarifying answers accumulate.
- In `_llm_plan`, include the same condensed history so the planner can see
  that earlier ambiguity was resolved and it is now time to propose
  `create_automation`.
- Check `api/routes/agent.py` `ask()` actually forwards `history` from the
  request body; fix if dropped.

### 3.5 Frontend: creation moves to chat

`osai-web/app/automations/page.tsx`:
- Replace (or supplement) the name/prompt/cadence form with a "Create with
  OSAI" chat entry point: reuse the existing Ask OSAI chat component (find it
  via the dashboard page's ask flow — `app/dashboard/page.tsx`) seeded with
  the user's automation request, keeping `conversation_id`/`history` across
  turns.
- Proposed actions already render with confirm buttons in the ask flow;
  verify `create_automation` proposals render there, and after a confirmed
  `create_automation`, refetch the automations list.

### 3.6 Tests

- Planner: ambiguous request ("summarize my stuff daily") → no actions;
  explicit request with cadence + source → `create_automation` proposed
  (heuristic path; LLM path mocked via `generate_json`).
- `confirm_action` with an internal `create_automation` descriptor creates a
  row (assert via `list_automations`) and is org-guarded (existing
  `org_mismatch` test pattern).

---

## Phase 4 — Automation runs that can actually answer (backend)

### 4.1 Run context

`api/routes/automations.py` `run_`:
- Build `connector_context(org_id)` (Phase 1) and a **delta block**: which
  documents were ingested since `auto.last_run_at`. Read
  `db/models.py` for the ingested-document model (search for the model used
  by `connectors/composio_ingest.py` when storing `SourceDocument`s) and add
  a repository function
  `list_documents_since(session, org_id, since: datetime | None, limit=50)`
  returning `(source_tool, title, created/ingested timestamp)` tuples.
- Prepend to the automation prompt:

```
Automation context:
{connector_context}
New items since last run ({last_run_at or "never"}):
- [googledrive] Q3 planning doc (2026-07-09)
- …or "No new items."
```

- Pass this via the `extra_context` param on `run_via_hermes` (Phase 1.2) and
  prepend to the question for the `run_ask` fallback.

### 4.2 The "new connector added" half of the user's request

The user asked for a summary of *new connectors* too. `connector_context`
lists current connections; the delta needs a baseline. Simplest correct
approach: store the connector list snapshot on each run —
add `last_connectors: Mapped[list | None] = mapped_column(JSON, nullable=True)`
to `Automation` (fold into the Phase 2 migration), set it in
`record_automation_run`, and include "Connectors added since last run: …" in
the run context by diffing.

### 4.3 Consent / missing-access behavior

When the automation prompt references a source that is not in the connected
list, the preamble (Phase 1.2) already instructs the agent to direct the user
to the Integrations page. Add one more preamble line:

```
- If the user must connect or grant access to a source, tell them exactly:
  "Connect it from Settings → Integrations, then re-run this automation."
```

(True OAuth-grant-from-chat is out of scope; the Composio connect flow at
`POST /integrations/composio/connect/{toolkit}` returns a redirect URL — a
follow-up can surface that as a button.)

### 4.4 Tests

- `list_documents_since` respects org + since filters.
- `run_` with a fake Hermes (httpx mock): assert the outbound prompt contains
  the connector list and the new-items block.

---

## Phase 5 — Frontend edit UI

`osai-web/app/automations/page.tsx`:
- Per-automation "Edit" affordance → dialog with name, prompt, cadence,
  enabled/paused; submits `PATCH /automations/{id}`. Follow the page's
  existing fetch/error/toast patterns and the design system
  (`osai-web/DESIGN.md`, `docs/design-system.md`).
- "Refine with OSAI" button per automation: opens the chat (Phase 3.5) seeded
  with `Update automation {id} ("{name}"): ` so the agent uses
  `update_automation`.
- Render `last_result` as formatted markdown (check which markdown renderer
  the ask flow already uses) instead of a raw log line, with the run time.
- Update `docs/api-contract.md` with the PATCH endpoint and new fields.

---

## Acceptance criteria (verify all before done)

1. Re-run the original scenario: with Google Drive connected via Composio, an
   automation "daily summary of any new connector I add and any new
   information that connector brings" run via `POST /automations/{id}/run`
   produces an answer that (a) names Google Drive as connected, (b) never
   mentions CLI/cron/Telegram, (c) summarizes or explicitly says there are no
   new items since last run.
2. In chat, "give me a daily summary of new connector info" with no further
   details → the answer asks 1–3 clarifying questions and proposes NO action;
   after the user replies with specifics, a `create_automation` action is
   proposed; confirming creates a visible automation with the right cadence.
3. `PATCH /automations/{id}` edits cadence/prompt; the edit UI works; a
   cross-org PATCH/confirm is rejected.
4. All new tests pass plus the existing suite: `cd osai-backend && pytest`.
5. `osai-web` builds: `cd osai-web && npm run build`.

## Out of scope (do not build now)

- Celery-beat scheduled execution of cadences (separate task; `run_` +
  cadence field are the seam).
- OAuth connect-from-chat button (noted in 4.3).
- Email/Slack delivery of automation results.
