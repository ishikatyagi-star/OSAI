# OSAI Codebase Audit — 2026-07-12

Audited against **origin/main @ 93126e5** (PR #141) via a clean worktree — NOT the local
checkout, which is stale (see Finding 0). Behavior was verified by running the real stack:
backend suite (196 passed / 6 skipped) against fresh Postgres+Qdrant+Redis containers,
`tsc --noEmit` (clean), all 3 web test files, and a live `uvicorn` boot with real HTTP
traces (login → JWT → /integrations → /dashboard/metrics → /ask with a real cited answer →
/team/members, plus cross-org spoof probes, which were correctly rejected).

Severity legend: **BLOCKER** = looks wired but doesn't work · **DEAD** = safe to delete ·
**RISKY** = works but fragile/untested · **COSMETIC**.

This file is a working artifact for the cleanup execution — delete it when done.

---

## Finding 0 — the local checkout is stale (BLOCKER for execution, fix first)

- Local repo is on `feat/connector-catalog` (ends at PR #118 + 1 commit `91d43d0`);
  `origin/main` is ~20 merged PRs ahead (through #141).
- Local uncommitted state: 5 legacy plan files deleted (`OSAI_BUILD_ROADMAP.md`,
  `OSAI_EXECUTION_PLAN.md`, `OSAI_MVP_BUILD_PLAN.md`, `OSAI_PARALLEL_PLAN.md`,
  `OSAI_MVP_Build_Brief.docx`), modified `render.yaml` + `osai-web/next-env.d.ts`,
  3 untracked active plan docs (`AGENTIC_AUTOMATIONS_PLAN.md`,
  `PRODUCTION_READINESS_ACTION_PLAN.md`, `PROMPTQL_GAP_PLAN.md` — keep these).
- **Every fix below must be applied on top of origin/main.** Step 0 of the execution plan
  is to reconcile/stash the local edits and check out main. Do NOT execute fixes on the
  stale branch.

---

## Phase 1 — Inventory & Map

~265 tracked files, ~21.6k LOC. Monorepo: `osai-backend/` (FastAPI + SQLAlchemy + Alembic +
Celery + Qdrant), `osai-web/` (Next.js 16 App Router), `services/` (hermes-sidecar FastAPI
wrapper + 2 git submodules), `evals/` (frontend-lane scaffold), `docs/`, `.agents/`.

### Directory map (purpose per area)
| Area | Purpose |
|---|---|
| `osai-backend/api/main.py` | FastAPI app; registers all 27 routers (all registered, none orphaned) |
| `osai-backend/api/routes/*` | 26 route modules (health, auth, agent/ask, documents, integrations, composio, automations, threads, wiki, sql, slack_ask, webhooks, team, orgs, settings, graph, search, decisions, feedback, notifications, artifacts, dashboard, evals, sync_runs, workflows, workflow_actions) |
| `osai-backend/agent/*` | Ask orchestrator, tools, context, hermes client, automation runner, Slack delivery |
| `osai-backend/connectors/*` | Native connectors (notion/slack/gdrive/freshdesk), Composio tool+ingest layer, registry, sync service |
| `osai-backend/memory/*` | Chunker, embeddings, Qdrant store, retriever, org memory, Supermemory + gbrain clients |
| `osai-backend/llm/*` | gemini.py, ollama.py (red-tier local), policy.py (routing policy), **router.py = DEAD** |
| `osai-backend/db/*` | models, repositories, session/auth deps, seed, 22 migrations |
| `osai-backend/workers/*` | Celery app + ingest/extract/execute/automations tasks (registered via string includes) |
| `osai-backend/workflows/*` | Action-item extraction runner + prompts |
| `osai-backend/evals/*` | Real eval runner + fixtures + hermes_export CLI |
| `osai-backend/tests/*` | 51 test files, 196 tests — all passing |
| `osai-web/app/*` | 24 routes; 5 are intentional redirects (search, board, evals, settings/data-routing → see BLOCKER B3) |
| `osai-web/components/*`, `lib/*` | UI + API client; orphans listed below |
| `services/hermes-sidecar/` | Authed HTTP wrapper around hermes CLI (auth verified: 401 without X-Sidecar-Token) |
| `services/gbrain`, `services/hermes` | git submodules |
| `evals/` (top level) | Mock-only scoring scaffold, never wired to real /ask (run_evals.py:63 TODO) |
| `.agents/tasks/**` | Stale AI-agent task scaffolding (22 files, some dated 2025-01-27) |

### Orphans (zero inbound references — verified by import scan)
| File | Note | Severity |
|---|---|---|
| `osai-web/components/graph/graph-canvas.tsx` | Old entity-graph canvas; graph page now renders access map only | DEAD |
| `osai-web/lib/graph-layout.ts` | Only consumer is graph-canvas (transitively dead) | DEAD |
| `osai-web/lib/graph-meta.ts` | Same | DEAD |
| `osai-web/components/workflow-status.tsx` | Unimported | DEAD |
| `osai-web/components/source-citation.tsx` | Unimported (superseded by `ask/citation-chip.tsx`) | DEAD |
| `osai-web/components/connector-card.tsx` | Unimported (superseded by `integrations/connector-manager.tsx`) | DEAD |
| `osai-web/components/ui/scroll-area.tsx` | Unimported; its npm dep goes with it | DEAD |
| `osai-web/components/ui/tabs-pill.tsx` | Unimported | DEAD |
| `osai-web/components/ui/skeleton.tsx` | Unimported | DEAD |
| `osai-backend/llm/router.py` | 31-line placeholder (`model="configured-later"`), never imported; real routing lives in `llm/policy.py` | DEAD |
| `osai-backend/connectors/stubs.py` | StubConnector never imported (registry uses real connectors) | DEAD |
| `evals/` (top-level dir) | Mock-fixture scaffold duplicating `osai-backend/evals`; never wired (run_evals.py:63 TODO) | DEAD (confirm with co-founder — it was the frontend lane's) |

---

## Phase 2 — Dead Code Detection

Clean overall: `ruff` passes (CI-enforced), **zero** stray `print()`/`console.log`, **zero**
commented-out code blocks found in either codebase.

| # | Finding | Location | Severity |
|---|---|---|---|
| D1 | Unreachable code after `return` in all 4 native connectors' sync loops | `connectors/freshdesk.py:89`, `connectors/google_drive.py:92`, `connectors/notion.py:64`, `connectors/slack.py:84` | DEAD |
| D2 | `openai_api_key` config field never read anywhere (comment even says "legacy") | `osai-backend/config.py:168` | DEAD |
| D3 | 8 unused exports in the web API client: `getTierRules`, `putTierRules`, `postSearch`, `getDataRouting`, `patchDataRouting`, `getGraphEntities`, `getGraphEdges`, `getDocumentAccess` | `osai-web/lib/api.ts` | DEAD (but see B3 — two of these are half of an orphaned feature) |
| D4 | Backend endpoints with no callers (not web UI, not external, not internal): `POST /search` (search.py:17), `GET /graph/entities` (graph.py:46), `GET /graph/edges` (graph.py:80), `GET+PUT /integrations/{k}/tier-rules` (integrations.py:168,176), `GET+PATCH /settings/data-routing` (settings.py:28,41), `GET /feedback` (feedback.py:91, test-only), `GET /integrations/composio/tools` (composio.py:39), `POST /integrations/composio/sync` (:96), `GET /integrations/composio/connections` (:102), `POST /integrations/composio/{toolkit}/ingest` (:115), `GET /sql/sources/{id}/schema` (sql.py:123, test-only) | see refs | DEAD-candidate — decide per endpoint: delete, or keep as deliberate API/ops surface (then document in docs/api-contract.md) |
| D5 | `currentOrgId()` helper duplicated inline twice before its definition | `osai-web/lib/api.ts:443,465` vs `:494` | COSMETIC |
| D6 | Unused var `vectors_config` | `osai-backend/tests/test_memory_qdrant.py:17` | COSMETIC |
| D7 | Unused npm dep `@radix-ui/react-scroll-area` (only consumer is orphaned scroll-area.tsx) | `osai-web/package.json` | DEAD (remove together with the orphan) |

Non-findings worth recording so nobody "fixes" them: `workers/tasks/*` look unimported but
are registered via Celery string includes (`workers/celery_app.py`); `db/seed.py` is the CI
`python -m db.seed` entrypoint; `redis` + `python-multipart` have no direct imports but are
required by Celery broker / FastAPI multipart forms; `llm/ollama.py` is live (red-tier local
generation via `memory/retriever.py:202`).

---

## Phase 3 — Wiring Verification

### Verified working end-to-end (live HTTP against booted stack)
- Auth: `/auth/login` (local email path) → JWT → org scoping. **Tenant isolation is
  correctly enforced**: org always comes from the verified JWT; body-supplied `org_id` is
  overwritten (`agent.py:32`, `search.py:23`, `workflows.py:74`); `X-Org-Id` is honored only
  for the public `demo-org` (`db/session.py:56-70`). Spoof probes returned 401.
- `/ask` returns a real, cited answer from seeded org memory. `/integrations`,
  `/dashboard/metrics`, `/team/members` all return correct live data.
- Config guards are real: prod boot refuses weak JWT secret and unauthenticated Hermes
  sidecar (`config.py:24-53`); hermes-sidecar itself 401s without `X-Sidecar-Token`.
- SQL answers: `ensure_readonly_select` (sql.py:33) + `SET TRANSACTION READ ONLY` + LIMIT
  cap — solid for a pilot.
- The remaining features (upload, threads, wiki, artifacts, automations CRUD, decisions,
  notifications, team invites) are exercised through FastAPI TestClient in the 196-test
  suite, which ran green against real Postgres/Qdrant/Redis.

### BLOCKER findings
| # | Finding | Location |
|---|---|---|
| B1 | **Inbox is a demo-only shell.** Real orgs get `items = []` — no fetch, no backend endpoint exists. Filters + CSV export operate on nothing, yet it's linked in the main sidebar. Wire it to a real source or remove it from the sidebar. | `osai-web/app/inbox/page.tsx:16-18`; link in `components/sidebar.tsx` |
| B2 | **Dashboard "needs attention" section is demo-only** (`attentionItems = demo ? DEMO_ATTENTION_ITEMS : []`) — permanently empty for real orgs while looking like a feature. | `osai-web/app/dashboard/page.tsx:59` |
| B3 | **Data-routing redirect goes to a tab that doesn't exist.** `/settings/data-routing` redirects to `/integrations?tab=routing`, but the integrations page has zero tab handling. The per-connector tier-rules feature has no UI at all anymore — its 4 api.ts functions (D3) and 4 backend endpoints (D4) are stranded. Either rebuild the routing UI or remove redirect + endpoints + client functions coherently. | `osai-web/app/settings/data-routing/page.tsx:6`; `app/integrations/page.tsx` |
| B4 | **Scheduled automations never fire in production.** Cadences (hourly/daily/weekly) run only via Celery beat (`workers/celery_app.py:28-34`), and `render.yaml` deliberately deploys no worker (lines 9-11: free tier). The UI sells cadences with no disclosure; only manual "Run now" works in prod. Fix = deploy the worker, or an in-API scheduler fallback, or honest UI copy. | `render.yaml:9-11`; `osai-web/app/automations/page.tsx` |
| B5 | **Zoom webhook is half-wired and unauthenticated in prod.** (a) Signature check is bypassed entirely when `OSAI_ZOOM_WEBHOOK_SECRET` is unset (`webhooks.py:30-32`) and render.yaml never sets it → anyone can POST fake events. (b) Ingestion is hardcoded to `settings.default_org_id` = demo-org (`webhooks.py:125`) — it can never deliver a real customer's meetings to their org. (c) It enqueues `download_and_transcribe.delay(...)` which nothing consumes in prod (no worker, see B4). Effectively decorative in production while exposing an open endpoint. | `osai-backend/api/routes/webhooks.py:30,125` |
| B6 | **The web test suite fails on main** — see Phase 4, T1. | `osai-web/tests/landing-page.test.mjs:60` |

### RISKY findings
| # | Finding | Location |
|---|---|---|
| R1 | `apiGet` swallows every failure (timeout, 500, network) into the fallback value — a broken backend is indistinguishable from an empty workspace on every list page. Deliberate design, but there is no logging/telemetry at all; at minimum add a dev-visible `console.warn` or error state. | `osai-web/lib/api.ts:71-77` |
| R2 | `NextResponse.redirect("/dashboard")` in the catch branches uses a relative URL — `NextResponse.redirect` requires an absolute URL and would throw if that branch ever runs (missing html file). | `osai-web/app/landing/route.ts`, `app/saas/route.ts`, `app/universities/route.ts` |
| R3 | Login page Terms of Service / Privacy Policy links are `href="#"` no-ops — legal links that go nowhere on the signup surface. | `osai-web/app/login/page.tsx:117` |
| R4 | SQL source DSNs (with passwords) are stored in plaintext in Postgres (`sql_sources.dsn`). Masked in API responses (`sql.py:_mask`) but not at rest. Acceptable for pilot — flag for launch. | `osai-backend/db/models.py:380-388` |
| R5 | SQL read-only guard is regex/blocklist-based. `SET TRANSACTION READ ONLY` is the real backstop and is present, but volatile/side-effectful functions in SELECT are still callable; also no statement timeout beyond `connect_timeout`. Add `options=-c default_transaction_read_only=on -c statement_timeout=10000` to the engine for defense in depth. | `osai-backend/api/routes/sql.py:33-52,60-63` |

---

## Phase 4 — Testing

**Backend: healthy.** 196 passed, 6 skipped (4 need `OSAI_COMPOSIO_API_KEY`, 2 need a local
gbrain/bun setup — both legitimately environment-gated), 1.8s, on fresh containers after
`alembic upgrade head` + seed. Coverage includes the paths that matter: auth isolation,
tier/clearance access, egress policy, tenant scoping, automations, sync, upload.

**Web: gaps.**
| # | Finding | Location | Severity |
|---|---|---|---|
| T1 | `landing-page.test.mjs` **fails on main**: the brand-copy guard (no em dashes, no visible "OSAI") is violated by 8 files added in recent PRs: `app/artifacts/page.tsx`, `app/ask/page.tsx`, `app/automations/page.tsx`, `app/settings/page.tsx`, `app/sql/page.tsx`, `app/wiki/page.tsx`, `components/ask/composer-attach.tsx`, `components/ask/file-card.tsx`. Fix the copy (replace em dashes per the guard's intent), do NOT weaken the test. | `osai-web/tests/landing-page.test.mjs:60` | BLOCKER |
| T2 | `npm test` only runs 1 of 3 test files — `ask-conversation.test.mjs` and `ask-page.test.mjs` exist, pass, and are never run by the script. | `osai-web/package.json:9` | RISKY |
| T3 | **No web CI at all** — `ci.yml` triggers only on `osai-backend/**`. That is exactly why T1 shipped: nothing runs `tsc` or the web tests on PRs. Add a web job (install → tsc → all tests). | `.github/workflows/ci.yml:4-10` | RISKY |
| T4 | Zero-coverage note: web component logic (message-bubble rendering, connector-manager state) has no tests. Backend `agent/delivery.py`, `webhooks.py` are covered. Given pilot stage, add web tests opportunistically, not exhaustively. | — | COSMETIC |

Test infra exists on both sides; no setup work needed beyond the CI job (T3).

---

## Phase 5 — Documentation Cleanup

| # | Item | Action | Severity |
|---|---|---|---|
| M1 | `OSAI_BUILD_ROADMAP.md`, `OSAI_EXECUTION_PLAN.md`, `OSAI_MVP_BUILD_PLAN.md`, `OSAI_PARALLEL_PLAN.md`, `OSAI_MVP_Build_Brief.docx` (repo root) | Delete — already deleted locally (uncommitted); commit that deletion on main | DEAD |
| M2 | `.agents/tasks/**` (22 files of AI-task scaffolding, incl. reviews misdated 2025-01-27) | Delete directory | DEAD |
| M3 | Top-level `evals/` incl. `fixtures/README.md` | Delete with the scaffold (Phase 1) — **confirm with co-founder first** (it was S11's lane) | DEAD |
| M4 | `osai-web/DESIGN.md`, `osai-web/elevenlabs/DESIGN.md`, `osai-web/framer/DESIGN.md` | 3 competing design docs — **ask before deleting** (co-founder's lane); at most one should survive | ASK |
| M5 | `docs/api-contract.md` | Verify against the real route table (Phase 1 map) and update — it predates threads/wiki/sql/slack-ask/artifacts | RISKY (stale docs) |
| M6 | Keep: `README.md`, `CONTRIBUTING.md`, `docs/deploy.md`, `docs/design-system.md` (verify freshness), `osai-backend/README.md`, `services/hermes-sidecar/README.md+DEPLOY.md`, `workflows/prompts/action_item_extraction.md` (it's a prompt, not doc), the 3 untracked active plan docs, `.github/pull_request_template.md` | — | — |
| M7 | Outdated comments: none found describing behavior the code no longer has (comment discipline is unusually good — comments are "why"-style). Spot-fix during execution if encountered. | — | COSMETIC |

---

## Phase 6 — Consistency & Presentation

| # | Finding | Severity |
|---|---|---|
| C1 | Naming is already consistent: kebab-case web files, snake_case Python, camelCase TS functions. No action. | — |
| C2 | Error handling: backend is consistent (HTTPException + `try_db` best-effort + annotated broad-catches). Web has a deliberate GET-swallow / POST-throw split — keep the split but fix observability (R1). | RISKY |
| C3 | Two dashboard pages: `/dashboard` (home, partly demo-gated — see B2) and `/dashboards` (analytics/metrics, real data). Both in sidebar under different labels. Works, but names are confusingly similar — consider renaming route `/dashboards` → `/analytics` with a redirect. | COSMETIC |
| C4 | `evals` exists three times (top-level scaffold, `osai-backend/evals`, `api/routes/evals.py`) — resolved by M3. | COSMETIC |
| C5 | Unused deps: web `@radix-ui/react-scroll-area` (D7). Backend: none (all justified). | DEAD |
| C6 | Uncommitted local edits to `render.yaml` and `osai-web/next-env.d.ts` in the working tree — review, then commit or discard during step 0. | RISKY |

---

## Prioritized Execution Plan

Each phase should end green: backend pytest, web `tsc` + all 3 test files.

**Step 0 — Sync the checkout (do first, by hand, not sonnet):**
stash/commit local edits, review the `render.yaml` diff, check out `main`, pull. Keep the
3 untracked plan docs. Commit the already-made deletion of the 5 legacy plan files (M1).

**Phase A — BLOCKERs (highest value, most user-visible):**
1. T1: fix the 8 brand-copy violations → web suite green.
2. T2+T3: `npm test` runs all test files; add web CI job (install, tsc, tests).
3. B1: decide inbox (remove from sidebar + delete page, or wire to a real endpoint). Removal recommended for now — no backend exists.
4. B2: remove or wire the dashboard "needs attention" demo block.
5. B3: fix `/settings/data-routing` redirect target; decide tier-rules feature fate (rebuild UI vs remove endpoints+client fns).
6. B4: automations cadence honesty — pick: deploy worker (paid), in-API scheduler, or UI disclosure. Interim: UI disclosure.
7. B5: zoom webhook — require the secret in non-local env (mirror the `hermes_sidecar_token` guard in config.py), and either finish org routing or feature-flag the endpoint off.

**Phase B — DEAD deletions (mechanical, low risk):**
D1 unreachable code ×4 · D2 config field · D3 unused api.ts exports (minus any revived by B3 decision) · D4 endpoint decisions · D5 dedupe currentOrgId · D6 · D7 + orphaned components (Phase 1 table) · M1-M3 doc deletions (M3/M4 after confirmation).

**Phase C — RISKY hardening:**
R1 apiGet observability · R2 absolute redirect URLs · R3 real ToS/privacy links (or remove the sentence) · R5 SQL engine read-only session opts · M5 api-contract refresh.

**Phase D — COSMETIC:** C3 rename, T4 opportunistic tests.

## Open questions (need your call, flagged not guessed)
1. Inbox (B1): remove or build? Removal is reversible via git.
2. Tier-rules / data-routing (B3): is per-connector tiering still a product feature post-visibility-model (PR #131)? If not, delete backend surface too.
3. Automations in prod (B4): pay for the Render worker, or ship UI disclosure for the pilot?
4. Dead endpoints (D4): any kept intentionally as ops/API surface? Zoom webhook especially — half-built; delete or finish?
5. M3/M4 doc deletions touch the co-founder's lane — confirm before deleting.
