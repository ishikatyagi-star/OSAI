# PromptQL Gap-Closure Plan (July 2026)

Goal: close the 8 gaps identified vs PromptQL (promptql.io), with Supermemory
(supermemory.ai) as the memory/context backbone. One PR per feature, priority
order below. OSAI stays org-level: everything respects the visibility-grant
model (PR #131) and data-tier routing.

## Supermemory as the memory layer

- Client: `osai-backend/memory/supermemory_client.py`, env-gated:
  `OSAI_SUPERMEMORY_API_KEY` (+ `OSAI_SUPERMEMORY_URL` for the self-hosted
  binary). Absent → graceful fallback to the existing Postgres org-memory.
- Container tags: `org:<org_id>` for shared team memory, `user:<user_id>` for
  personal context (mirrors our grant model). Same pool, flexible mixing.
- **Sovereignty rule:** only normal-tier content may go to Supermemory cloud;
  amber/red requires the self-hosted deployment. Enforced in the client.
- APIs used: `POST documents` (add), `search`, `update/forget memory`,
  user profiles.

## PRs in priority order

| # | Feature (gap) | Shape |
|---|---|---|
| A | **Supermemory foundation** | Client + fallback, org/user container tags, wire into retriever context (replaces/augments `org_memory.fetch_relevant`). |
| B | **Corrections that persist** | Thumbs-down gains "correct it" text box → stored as correction memory (Supermemory) + linked to retrieval trace. Retriever injects matching corrections as authoritative context; answer notes "corrected by <user>". Whole-team effect. |
| C | **Shared threads** | Persist Ask conversations server-side (`threads` table). Thread list sidebar, org-shareable link (respects grants), teammates can continue a thread. @mention agent = normal ask; @mention teammate = notification (reuses PR #131 notifications). |
| D | **Org wiki ("Context" page)** | Versioned wiki entries (Postgres revisions) + Supermemory indexing so Ask cites wiki. "Suggested updates": decisions logged + corrections surface as draft wiki edits to approve. |
| E | **Persistent artifacts** | Save answer artifacts (tables/briefs/charts) per org; Artifacts page; "pin to thread" and reuse as context in new asks; export CSV/MD. |
| F | **Automations as APIs** | Per-automation trigger endpoint + scoped token (`POST /automations/{id}/trigger`); webhook-style invocation from external systems; run-result JSON. PromptQL "Program API" equivalent. |
| G | **Structured-data querying** | Phase 1: Postgres connector — schema introspection → LLM writes SQL → **plan shown before execution**, deterministic run, results as artifact. Phase 2: warehouse targets (Snowflake/BigQuery). This also covers gap #5 (plan-level transparency: visible, editable, re-runnable SQL). |
| H | **Onboarding & surfaces** | Managed demo LLM key w/ free credits; Slack app as a client (ask from Slack, not just delivery). Desktop/mobile explicitly deferred. |

## Non-goals (for now)
- Full DSL/deterministic planner across all connectors (PromptQL's core bet) —
  we get 80% via G's visible-SQL approach.
- Native desktop/mobile apps.

## Status
- [x] A — Supermemory foundation (PR #133)
- [x] B — Corrections loop (PR #134)
- [x] C — Shared threads (PR #135)
- [x] D — Org wiki (PR #136)
- [x] E — Persistent artifacts (PR #137)
- [x] F — Automation trigger API (PR #138)
- [x] G — SQL querying phase 1 (PR #139); phase 2 (warehouses) open
- [x] H — Slack /ask client (PR #140); managed-demo-key onboarding deferred
