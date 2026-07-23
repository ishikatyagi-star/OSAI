# OSAI — Production Readiness Audit & Action Plan

> [!WARNING]
> **Historical snapshot (2026-07-04).** This document preserves the evidence and
> proposed work from that audit; it is not the current source of truth. Many
> findings and deployment assumptions have since changed. Verify every item
> against the current code, tests, [README](README.md), and
> [deployment guide](docs/deploy.md) before acting.

**Prepared by:** Senior-engineer + product-design audit pass (Fable 5)
**Date:** 2026-07-04
**Repo audited:** `/Users/ishikatyagi/Documents/Projects/Osai/OSAI` (backend `osai-backend/`, frontend `osai-web/`)
**Method:** Full code read of backend routes/services and frontend pages; backend lint (`ruff` — clean) and test suite (`pytest` — 50 passed, 1 failed, 2 skipped); frontend `tsc --noEmit` (clean); live run of API (`:8000`) + web (`:3000`) against Dockerized Postgres/Redis/Qdrant; manual browser walkthrough of every core screen at desktop + mobile widths; and direct `curl` probing of the API to reproduce auth/isolation behavior.

> **Historical use only:** Item IDs are retained for cross-reference to the July 4 audit. The observations and suggested order below describe that snapshot, not the current branch. Anything marked `[INFERRED]` was reasoned from code but not independently reproduced at audit time.

---

## 1. Executive Summary

OSAI is an ambitious, genuinely functional product: a RAG-over-connected-tools "company brain" with an Ask agent, propose/confirm actions, workflow extraction, a live dashboard, team/dept management, Composio-based OAuth ingestion, and real Google sign-in. The backend is clean, typed, lint-passing, and mostly well-tested. The frontend typechecks and the happy-path demo looks polished on desktop. **This is a strong MVP/demo. It is not yet safe for a real production, multi-tenant deploy.**

**The single biggest risk is tenant isolation.** The core data endpoints — `POST /search`, `POST /ask`, `POST /ask/actions/{id}/confirm`, `POST /workflows`, and the workflow action-item approve/execute endpoints — **perform no authentication and trust the `org_id` supplied in the request body.** I reproduced this live: an unauthenticated `curl` to `/search` and `/ask` with an arbitrary `org_id` returns that org's indexed knowledge and proposes real connector actions. Any user (or anyone on the internet who can reach the API) can read any organization's data and drive its agent. This is a blocker for onboarding a second real customer.

**Second-tier risks:** a hardcoded insecure default JWT signing secret (forgeable sessions if the env var is ever unset in prod); a client-side trust bug where the Ask UI fabricates a fake "executed" action with a fake ticket URL when a real action-confirmation fails (even outside demo mode); no async worker on the production (Render free) deploy, so ingestion runs synchronously in the request and a real sync will time out / OOM; and a completely broken mobile layout (fixed sidebar consumes ~60% of a phone viewport with no collapse).

**UI/UX** is above-average for a solo/small-team build but has clear "unfinished" tells: no error/empty/loading boundaries at the app level (a thrown render error shows Next.js's raw error screen), a permanent hardcoded green "LIVE — actively syncing" badge that lies about state, a non-functional "Export" button, horizontal overflow on the Org Graph and dashboard tiles, and demo-fixture numbers (e.g. "1,247 sources") bleeding into what looks like a real signed-in workspace because the seeded admin lives in the shared `demo-org`.

**Hermes is confirmed in scope for launch** (product decision). This is the one item that is a genuine *workstream* rather than a tightening: the OSAI-side seam is fully built and rollback is one env var, but the sidecar has never been run end-to-end, it's only wired into Automations (not the main Ask flow), and its silent-fallback design becomes a monitoring blind spot once you're launching *on* it. It also hard-depends on the SEV-001 auth fix for its isolation guarantee to hold. See SEV-401 and Phase 5.

**Rough effort estimate:** The blockers are small, surgical code changes (auth dependencies already exist — `get_org_id`, `get_claims` — they just aren't applied to the leaky routes). Call it **~2–3 focused days for Phase 1 (blockers) + Phase 2 (integration/security)**, **~3–5 days for the UI/UX overhaul and hardening**, and **~2–3 days for the Hermes launch workstream (Phase 5)** which can partly overlap the UI work. The architecture is sound; this is tightening, not rebuilding.

**Test/build status at audit time:**
- Backend `ruff check .` → **clean**.
- Backend `pytest` → **50 passed, 1 failed, 2 skipped**. The one failure (`tests/test_onboarding.py::test_api_auth_login`) is a stale test asserting the old `mock-jwt-token-{id}` format; the code now issues real JWTs. See `SEV-201`.
- Frontend `tsc --noEmit` → **clean**.
- App boots and all core screens render against live infra.

---

## 2. Blockers
*(Would break the product in real production or during a serious demo. Fix first.)*

---

### SEV-001 — Core data endpoints have no authentication and trust body `org_id` (cross-tenant data leak)
- **Category:** Security
- **Severity:** Blocker
- **Location:**
  - `osai-backend/api/routes/search.py` (`POST /search`)
  - `osai-backend/api/routes/agent.py` (`POST /ask`, `POST /ask/actions/{action_id}/confirm`)
  - `osai-backend/api/routes/workflows.py` (`POST /workflows` — `create_workflow` reads `request.org_id` from the body, not `get_org_id`)
  - `osai-backend/api/routes/workflow_actions.py` (`POST /workflows/{run_id}/action-items/{item_id}/approve` — no auth dependency at all)
  - Schemas that carry a client-supplied org: `api/schemas/search.py` (`SearchRequest.org_id`), `api/schemas/agent.py` (`AskRequest.org_id`), `api/schemas/workflow_run.py` (`WorkflowRunCreate.org_id`)
- **What's wrong:** These routers declare no `Depends(get_org_id)` / `Depends(get_claims)`. The org is taken from the JSON body. I reproduced this against the live server with no auth header:
  - `curl -s -X POST localhost:8000/search -d '{"org_id":"demo-org","query":"data tiering rules"}'` → returned the org's indexed documents and a synthesized answer with citations (HTTP 200).
  - `curl -s -X POST localhost:8000/ask -d '{"org_id":"demo-org","question":"who owns VPC setup"}'` → returned an agent answer (HTTP 200) and would propose connector actions.
  - `curl -s -X POST localhost:8000/workflows -d '{"org_id":"demo-org","input_text":"...","destination":"manual"}'` → HTTP 200, created a workflow run.
  Contrast with the correctly-guarded routes (`/dashboard/metrics`, `/integrations`, `/graph/*`, `/team/*`, `/automations`, `/sync-runs`, `/settings/*`) which use `Depends(get_org_id)` and returned **401** to the same unauthenticated probes. So the pattern for doing this right already exists in the codebase (`db/session.py::get_org_id`) — it simply was not applied to these five routes.
- **Why it matters:** With more than one real org in the database, any authenticated user (or any anonymous caller who can reach the API URL) can read another organization's entire knowledge base and drive its Ask agent / create workflows simply by passing a different `org_id`. This is a textbook broken-object-level-authorization / IDOR vulnerability and a hard blocker for a multi-tenant pilot. It also means the `retrieve_answer` permission filter (`memory/retriever.py::_visible`) is bypassed, because `SearchRequest.requester_permissions` defaults to empty → treated as admin/system context that "sees all".
- **Fix instructions:**
  1. In `db/session.py`, `get_org_id` already resolves the org from the verified JWT (and only trusts `X-Org-Id` for the public `demo-org`). Reuse it everywhere below.
  2. **`/search`:** Change the route to depend on `get_org_id` and on the caller's identity. Remove `org_id` from `SearchRequest` (or ignore it) and set `request.org_id = Depends(get_org_id)` server-side. Populate `requester_permissions` from the JWT claims (look up `User.permissions` by `claims["sub"]`, mirroring `automations.py::run_`) so the `_visible` governance filter actually applies per-user instead of defaulting to "see all".
  3. **`/ask` and `/ask/actions/{id}/confirm`:** Same treatment. `run_ask` currently takes `AskRequest.org_id` from the body — instead inject `org_id` from `get_org_id` in the route and pass it into the orchestrator. For `confirm`, verify the proposed action's stored `org_id` (in `agent/orchestrator.py::_PROPOSED[action_id]["org_id"]`) matches the caller's resolved org before executing; reject with 403 otherwise.
  4. **`/workflows` POST:** Add `org_id: Annotated[str, Depends(get_org_id)]` and use it instead of `request.org_id`. Drop/ignore the body field.
  5. **`/workflows/{run_id}/action-items/{item_id}/approve`:** Add `Depends(get_org_id)`; after loading the run, assert `run["org_id"] == resolved_org_id` before executing any connector action (this endpoint pushes to Freshdesk/Slack/Notion — executing it cross-tenant is worse than a read leak).
  6. Keep the public `demo-org` path working (the `X-Org-Id: demo-org` allowance in `get_org_id`) so the "Try Demo" experience is unaffected.
  7. Update the frontend callers in `osai-web/lib/api.ts` (`postSearch`, `askOsai`, `postWorkflow`) — they currently send `org_id` in the body from `localStorage`. They can keep sending it (harmless, ignored) or be cleaned up; the Bearer token in `getHeaders()` is what will now carry identity.
- **Acceptance criteria:**
  - Unauthenticated `curl` (no `Authorization`, no `X-Org-Id`) to `/search`, `/ask`, `/ask/actions/{id}/confirm`, `/workflows` (POST), and the approve endpoint returns **401**.
  - A user authenticated for org A who passes `org_id: "<org-B-id>"` in the body receives **only org A's** data (body value is ignored) — verified with two seeded orgs.
  - The `demo-org` public path still works with `X-Org-Id: demo-org` and no token.
  - `retrieve_answer` receives the caller's real `requester_permissions` and a non-admin user does not receive chunks they lack a permission grant for.
  - Existing tests still pass; add a regression test asserting cross-org body `org_id` is ignored.

---

### SEV-002 — Hardcoded insecure default JWT signing secret
- **Category:** Security
- **Severity:** Blocker
- **Location:** `osai-backend/config.py:30` — `jwt_secret: str = "dev-only-insecure-secret-change-me"`; used in `api/routes/auth.py::_issue_token` and `db/session.py::_decode_token`.
- **What's wrong:** The session-JWT signing key falls back to a well-known constant string committed to the repo if `OSAI_JWT_SECRET` is not set. `render.yaml` correctly declares `OSAI_JWT_SECRET` as a `sync: false` secret, but there is no runtime guard — if that env var is ever missing/empty in a real deployment, the app silently signs and accepts tokens with the public dev secret, so anyone can forge a valid session for any `sub`/`org_id`/`role` (including `role: admin`).
- **Why it matters:** Forgeable admin sessions completely defeat SEV-001's fix and every other auth check. A single misconfigured deploy is a full compromise.
- **Fix instructions:**
  1. In `config.py`, add a startup guard: when `env != "local"` (i.e., any non-local deployment) and `jwt_secret` equals the dev default (or is shorter than, say, 32 chars), raise a fatal error at import/startup so the service refuses to boot rather than running insecurely. Keep the dev default working only for `env == "local"`.
  2. Document generating a strong secret (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) in `README.md`/`docs/deploy.md`.
  3. Confirm the Render service actually has `OSAI_JWT_SECRET` set (it is `sync: false`, so it must be entered in the dashboard — verify it is non-empty in the live environment).
- **Acceptance criteria:**
  - Booting with `OSAI_ENV=production` (or any non-`local`) and no/weak `OSAI_JWT_SECRET` fails fast with a clear error.
  - Local dev (`OSAI_ENV=local`) still boots with the default.
  - A token signed with the dev secret is rejected by a production-configured instance.

---

### SEV-003 — Ask UI fabricates a fake successful action (with fake ticket URL) on confirmation failure
- **Category:** Integration/Bug (trust-critical)
- **Severity:** Blocker
- **Location:** `osai-web/app/ask/page.tsx`, `handleApprove` (~lines 217–247), the `catch` block.
- **What's wrong:** When the user clicks "Approve" on a proposed action and the real `confirmAgentAction` call throws (backend error, network failure, timeout, 401, etc.), the code **unconditionally** patches the action to `status: "executed"` and invents an `external_url` — e.g. `https://freshdesk.com/tickets/205` for Freshdesk, or `https://example.com/{tool}/created` for anything else. There is **no `isDemo()` guard** on this fallback (unlike the message-send path in the same file, which does check `isDemo()`). So in a real signed-in workspace, a failed "create Freshdesk ticket" action tells the user it succeeded and hands them a fabricated link to a ticket that does not exist.
- **Why it matters:** This is the worst class of bug for an "agent that takes actions": it silently lies about having performed a real side-effecting operation. A user believing a ticket/message was created when it wasn't will miss real work. It also fabricates a plausible-looking URL, which is actively misleading. This must never happen outside an explicitly-labeled demo.
- **Fix instructions:**
  1. Gate the fabricated-success fallback behind `isDemo()` (mirror the existing pattern used elsewhere in this file and in `send`). Import `isDemo` is already present.
  2. In non-demo mode, on a thrown/failed confirmation, patch the action to `status: "failed"` with a real error message (e.g. "Couldn't complete this action — please try again."), keep `requires_confirmation` appropriately, and surface a retry affordance. Do **not** set any `external_url`.
  3. Also handle the case where the backend returns a `ConfirmActionResult` with `status: "failed"` (the non-throw path) — ensure the UI shows the `error` string from the result rather than a success state.
- **Acceptance criteria:**
  - In a non-demo workspace, forcing the confirm call to fail (e.g. stop the backend) shows a clear failure state with no fabricated URL.
  - In demo mode, the canned-success behavior may remain (it is clearly a demo).
  - A backend `ConfirmActionResult{status:"failed"}` renders as a failure with its `error` message.

---

### SEV-004 — Mobile layout is broken (fixed sidebar overlays content, no responsive collapse)
- **Category:** UI/UX
- **Severity:** Blocker (for any mobile/tablet demo or field use)
- **Location:** `osai-web/components/app-shell.tsx`, `osai-web/components/sidebar.tsx`, and the layout CSS in `osai-web/app/globals.css` / `theme.css` (`.app-container`, `.sidebar`, `.dashboard-layout`).
- **What's wrong:** At 375×812 (mobile preset) the fixed-width sidebar occupies roughly 60% of the viewport and the main content is shoved off-screen and clipped (verified via screenshot: the "Dashboard" heading and the Company Pulse tile are cut off mid-word; the workspace name wraps to three lines in the top bar). There is no hamburger/drawer, no breakpoint that collapses or hides the sidebar, and no responsive stacking. The app is effectively unusable below ~900px wide.
- **Why it matters:** Any investor/customer who opens the link on a phone sees a broken product. Even if the primary target is desktop, a broken mobile first-impression undermines the "polished" positioning.
- **Fix instructions:**
  1. Add a responsive breakpoint (e.g. `max-width: 768px`) that converts the sidebar into an off-canvas drawer: hidden by default, toggled by a hamburger button added to the `.topbar` in `app-shell.tsx`. Use the existing Radix primitives already in the dependency list if helpful, or a simple CSS transform + overlay.
  2. Make `.dashboard-layout`/`main` full-width when the sidebar is collapsed; ensure the top bar's workspace label truncates with ellipsis instead of wrapping.
  3. Audit page-level grids (dashboard stat tiles, Org Graph table, Analytics tiles) to stack to a single column on narrow viewports.
- **Acceptance criteria:**
  - At 375px width, the sidebar is hidden behind a toggle, main content is full-width and not clipped, and no element causes horizontal scroll on the primary screens (Dashboard, Ask, Integrations, Sync Runs, Analytics, Team, Workflows, Settings).
  - At 768px and 1280px the layout remains correct.

---

### SEV-005 — Production ingestion still runs in the API process → real syncs can time out / OOM
- **Category:** Deployment / Integration
- **Severity:** Blocker for real (non-demo) ingestion at any volume
- **Location:** `render.yaml` now defines a paid worker for recurring automations, but `osai-backend/api/routes/integrations.py::_ingest_composio_in_background` and `api/routes/composio.py::_sync_in_background` still use FastAPI `BackgroundTasks`, which run **in the same web process/dyno**. The placeholder ingest/execute task names are not producers or real offload.
- **What's wrong:** On the free Render plan there is one web instance and no Celery worker. "Background" ingestion is FastAPI `BackgroundTasks` running inside the single web dyno. A real Composio sync (up to 25 files + media download + Whisper transcription + embeddings) is heavy; the code has already been patched twice (per commit history and inline comments) to dodge request-timeout/OOM 502s by deferring work to `BackgroundTasks`, but that still consumes the one web process's memory and CPU, and free-tier RAM is tight (the code even rejects >25MB media pre-emptively to avoid OOM). Under real load or larger corpora this will fail intermittently — which matches the "intermittent errors during integration testing" symptom reported.
- **Why it matters:** Ingestion is the core value loop. If it flakes under real data, the product doesn't work for actual customers, and the failures are non-deterministic (hard to debug, bad demo surprise).
- **Fix instructions:**
  1. **Short term (pilot):** Keep synchronous/`BackgroundTasks` ingestion but (a) enforce and document hard caps (file count, per-file size, total bytes) and (b) ensure every sync path records a `SyncRun` with a clear `partial`/`failed` status and error so the UI never silently hangs. Confirm `sync-runs` reflects in-flight and failed runs (it currently shows a `not_started` seed fallback — make sure real runs supersede it).
  2. **Real fix:** Implement a real Composio ingest Celery task plus producer, idempotency, retries, and terminal failure recording; then add its queue to the paid worker. The current hosted command intentionally consumes only `execute` because that is the only queue with an end-to-end producer/task contract. Redis is already provisioned (`osai-redis`).
  3. Add memory headroom / a bigger instance for the web service, or move ingestion entirely off the web dyno.
- **Acceptance criteria:**
  - A sync of a realistic corpus (e.g. 25 files including a media file) completes without a 502 and without OOM-killing the web process.
  - Every sync produces a terminal `SyncRun` row (`succeeded`/`partial`/`failed`) with an error message on failure, visible in `/sync-runs`.
  - `[INFERRED]` The OOM/timeout behavior is inferred from code + commit history + free-tier constraints; reproduce with a real Composio-connected account before/after the fix.

---

## 3. High Priority
*(Integration errors, broken flows, security gaps — fix right after blockers.)*

---

### SEV-101 — `POST /orgs` (org provisioning) is unauthenticated and unthrottled
- **Category:** Security
- **Severity:** High
- **Location:** `osai-backend/api/routes/orgs.py::create_org` — no auth dependency.
- **What's wrong:** Anyone can create arbitrary orgs + admin users. Reproduced: `curl -X POST /orgs -d '{"name":"EvilOrg","admin_email":"evil@example.com","admin_display_name":"Evil"}'` → HTTP 200, org created. This is intentional for self-serve onboarding, but combined with no rate limit and no email verification it's an abuse/spam vector and lets an attacker seed accounts.
- **Why it matters:** Unbounded resource creation on a free-tier DB; also the created admin email is unverified (a later Google sign-in with that email would `accept_invite`/join). Not catastrophic alone but should be gated before public launch.
- **Fix instructions:** Add a rate limit (per-IP) on `/orgs` and `/auth/login`. Consider requiring the org-creation path to go through Google OAuth (which verifies the email) for production, keeping the open form only for demo. At minimum, add basic input validation (valid email format, name length) and a captcha or per-IP throttle. A lightweight approach: add `slowapi` (or a simple in-memory/Redis limiter) middleware.
- **Acceptance criteria:** Rapid repeated `/orgs` or `/auth/login` calls from one IP are throttled (429). Invalid emails are rejected with 400.

---

### SEV-102 — `POST /auth/login` is a password-less email lookup (anyone can log in as any known email)
- **Category:** Security
- **Severity:** High
- **Location:** `osai-backend/api/routes/auth.py::login` — "Simulate a password-free lookup authentication"; returns a real signed JWT for any email that exists in the DB.
- **What's wrong:** The email/password form on the login page calls `/auth/login`, which issues a valid session for **any** email present in the `users` table with **no credential check**. So if an attacker knows a real user's email, they get that user's session (and org, and role). This is fine as a demo shortcut but is a real authentication bypass in production.
- **Why it matters:** Directly defeats tenant isolation for any known email address. Google OAuth (the real auth path) is solid; this legacy email-lookup path is the hole.
- **Fix instructions:** For production, disable the password-less `/auth/login` path (gate it behind `env == "local"` or a `demo` flag), and make Google OAuth the only real sign-in. If a non-Google email/password path is needed, implement actual password hashing (the `User` model has no password field today — this is a deliberate MVP shortcut). Update the login page to hide the email/password tab when the backend reports it is disabled (extend `GET /auth/config`).
- **Acceptance criteria:** In production config, `/auth/login` either returns 403/404 or requires a real credential; the login UI reflects availability via `/auth/config`. Demo/local still works.

---

### SEV-103 — Stale/misleading "LIVE — actively syncing" badge is hardcoded
- **Category:** UI/UX (honesty)
- **Severity:** High
- **Location:** `osai-web/components/app-shell.tsx` — the green `LIVE` pill with tooltip "Your workspace is actively syncing data from connected tools."
- **What's wrong:** The badge is a static literal. It shows "LIVE / actively syncing" even when zero connectors are connected and nothing is syncing (verified: the signed-in `demo-org` workspace shows "CONNECTED 0" on Integrations yet the top bar says LIVE + "actively syncing"). It's a decorative lie.
- **Why it matters:** Misrepresents system state to the user; erodes trust when they notice nothing is connected. Small but it's exactly the kind of detail that reads as "unfinished/fake."
- **Fix instructions:** Drive the badge from real state: query `getDashboardMetrics()` (or `/integrations`) and show "LIVE" only when `connectors_connected > 0` and/or a sync ran recently (`last_sync_at` within N hours). Otherwise show a neutral "No sources connected" / "Idle" state that links to Integrations. Remove the unconditional "actively syncing" copy.
- **Acceptance criteria:** With no connectors, the badge does not claim to be live/syncing. With a connected+recently-synced source, it shows LIVE.

---

### SEV-104 — Demo fixtures bleed into a real signed-in workspace via the shared `demo-org`
- **Category:** Integration/Bug + UX
- **Severity:** High
- **Location:** `osai-web/lib/demo.ts::isDemo()` (returns true when `localStorage.osai_org_id === "demo-org"`); `db/repositories.py::seed_demo_data` seeds the admin `admin@osai.local` into `demo-org`; many pages branch on `isDemo()` to show `DEMO_*` fixtures (`app/dashboard`, `app/sync-runs`, `app/integrations`, `app/inbox`, `app/decisions`, `app/dashboards`, `app/graph`, `app/workflows`).
- **What's wrong:** The seeded admin account (`admin@osai.local`) belongs to `demo-org`, and `isDemo()` treats **any** session in `demo-org` as demo mode. So signing in as the seed admin shows a mix of real aggregates and demo fixtures on the same screens — e.g. the Dashboard "Company Pulse" reads "1,247 sources indexed" (a `DEMO_STATS` number) while Analytics reads "5 documents" (real), and Sync Runs shows "TOTAL IN KNOWLEDGE BASE 1,247" (demo) next to "DOCS INDEXED (SESSION) 192" (real). The numbers contradict each other on the same workspace.
- **Why it matters:** Anyone using the seeded admin (a natural thing to do when testing) sees self-contradictory data and can't tell what's real. It also means the "real workspace" experience is never actually exercised through that account. This is very likely a contributor to the "found issues through manual testing" symptom.
- **Fix instructions:**
  1. Decide the contract: `demo-org` = always-demo public workspace; **real** customer orgs get UUID ids and never demo fixtures (this is already the intent per the design). The bug is that the *seeded internal admin* shares `demo-org`.
  2. Either (a) move the internal seed admin to a distinct non-demo org, or (b) accept that `demo-org` is demo-only and make the demo numbers internally consistent (don't mix `DEMO_STATS.documentsIndexed = 1247` with live `total_documents`). Preferably (a): create a separate seeded "real" test org so the live path is testable.
  3. Audit each page's `isDemo() ? DEMO_* : real` branch so that within one mode the displayed numbers are consistent (don't blend demo hero stats with live per-connector counts).
- **Acceptance criteria:** In a real (non-`demo-org`) workspace, every metric on Dashboard/Analytics/Sync Runs comes from the live API and they agree with each other. In `demo-org`, all numbers come from the demo fixtures and are mutually consistent.

---

### SEV-105 — No app-level error / not-found / loading boundaries (raw Next.js error screen on any thrown render)
- **Category:** UI/UX + Code Quality
- **Severity:** High
- **Location:** `osai-web/app/` — no `error.tsx`, `global-error.tsx`, `not-found.tsx`, or route-level `loading.tsx` exist (verified absent).
- **What's wrong:** Any uncaught exception during render (e.g. a malformed API payload that slips past a type assertion, or a `.map` over an unexpected shape) surfaces as Next.js's default error overlay in dev and a bare error page in prod. There is also no custom 404. Data fetches use per-call fallbacks in `lib/api.ts` (good), but rendering logic is unguarded.
- **Why it matters:** A single unexpected payload can white-screen a page in production with no graceful recovery or branding. Production apps need at least a friendly error boundary and 404.
- **Fix instructions:** Add `app/error.tsx` (client component with a reset button and a "something went wrong" message), `app/global-error.tsx`, and `app/not-found.tsx`, styled to match the app. Optionally add `loading.tsx` for routes that fetch on mount. Keep them minimal and on-brand.
- **Acceptance criteria:** Throwing inside a page renders the custom error boundary (not the Next default); navigating to a nonexistent route renders the custom 404.

---

### SEV-106 — Demo env-var name mismatch in `osai-web/.env.example`
- **Category:** Deployment / Code Quality
- **Severity:** High (config correctness)
- **Location:** `osai-web/.env.example` declares `NEXT_PUBLIC_DEMO_MODE=true` and `NEXT_PUBLIC_DEFAULT_ORG_ID=demo-org`; the code (`lib/demo.ts`) only reads `NEXT_PUBLIC_OSAI_DEMO`. `NEXT_PUBLIC_DEFAULT_ORG_ID` is not read anywhere.
- **What's wrong:** The documented env vars don't match what the code uses. A deployer setting `NEXT_PUBLIC_DEMO_MODE=false` to "turn off demo" achieves nothing (the real flag is `NEXT_PUBLIC_OSAI_DEMO`), and setting `=true` to enable a demo deploy also does nothing. Defaults happen to be safe (demo off), but the config surface is wrong and will cause confusion / a demo deploy that isn't in demo mode.
- **Why it matters:** Silent config no-ops are a classic source of "why isn't this working" and could ship a demo build that shows empty states, or a prod build the deployer thinks is non-demo but relied on the wrong var.
- **Fix instructions:** Reconcile the names. Either rename the code to read `NEXT_PUBLIC_DEMO_MODE` (and accept `"true"`/`"1"`), or fix `.env.example` to document `NEXT_PUBLIC_OSAI_DEMO=1`. Remove `NEXT_PUBLIC_DEFAULT_ORG_ID` if unused, or wire it. Keep one canonical name and update `README`/`docs/deploy.md`.
- **Acceptance criteria:** Setting the documented var actually toggles demo mode; `grep` shows no orphaned `NEXT_PUBLIC_*` names between code and `.env.example`.

---

### SEV-107 — `next.config.ts` redirects point at routes that were moved/removed
- **Category:** Bug / UX
- **Severity:** High `[INFERRED — verify each target]`
- **Location:** `osai-web/next.config.ts` `redirects()`.
- **What's wrong:** The redirect table maps `/data-routing → /settings/data-routing` and `/team-board → /board`. Per the project's own IA restructure, Data Routing now lives at `/integrations?tab=routing` (the `/settings/data-routing` page still exists but is described as superseded), and Team Board was folded into Decision Log. `/board` still exists as a page. So some redirects send users to deprecated/duplicate destinations, and there are two live surfaces for data routing (`/settings/data-routing` and `/integrations?tab=routing`).
- **Why it matters:** Duplicate/あいまい destinations confuse users and split maintenance; deep links may land on a stale page.
- **Fix instructions:** Decide the canonical location for each moved feature and make redirects point there consistently. If `/board` and `/settings/data-routing` are deprecated, redirect them to the canonical surfaces and delete the dead pages. Verify each `source`/`destination` resolves to the intended, single canonical route. (`[INFERRED]`: confirm current intent against the actual pages before deleting anything.)
- **Acceptance criteria:** Each legacy path redirects to exactly one canonical, live route; no two routes render the same feature; no redirect lands on a deleted page.

---

### SEV-108 — Fix the failing/stale auth test (and re-green the suite)
- **Category:** Code Quality / Test
- **Severity:** High
- **Location:** `osai-backend/tests/test_onboarding.py::test_api_auth_login` (asserts `data["token"] == f"mock-jwt-token-{data['user_id']}"`).
- **What's wrong:** The test encodes the old mock-token contract; the code now returns a real signed JWT (`api/routes/auth.py::_issue_token`). The suite is red (1 failed) which masks future regressions and blocks a clean CI gate.
- **Why it matters:** A permanently-red suite trains the team to ignore failures and defeats CI as a safety net — especially important given the auth changes in SEV-001/002.
- **Fix instructions:** Update the assertion to validate a real JWT: decode `data["token"]` with `OSAI_JWT_SECRET`/HS256 and assert `sub == user_id`, `org_id`, `role == "admin"`, and an `exp` in the future. Do not re-introduce the mock format.
- **Acceptance criteria:** `pytest` → all pass (0 failed); the updated test verifies JWT claims, not a string prefix.

---

## 4. UI/UX Overhaul List
*(Organized by screen, ordered by user-facing impact. These are polish/consistency items beyond the blockers above.)*

### 4.1 Global / Shell
- **SEV-201 — Non-functional "Export" button (Context Inbox).** `app/inbox/page.tsx:45` renders a primary "Export" button with no `onClick`. Either implement CSV/JSON export of the visible items or remove it. Dead primary buttons read as broken. **Accept:** button either exports or is gone.
- **SEV-202 — Horizontal overflow on wide tables/tiles at desktop.** The Org Graph access matrix (`app/graph/page.tsx`) clips its last tool column ("Google Drive" cut off) even at 1280px; the dashboard "Company Pulse" tile also clips on narrower desktops. Add horizontal scroll containers or responsive column collapsing. **Accept:** all columns reachable; no clipped content at 1280px.
- **SEV-203 — Consistent empty states.** Several pages default to `[]` in non-demo mode (Inbox, Decisions, Team invites/departments) but the empty rendering varies from a bare page to a styled state. Establish one reusable `<EmptyState>` component (icon + title + one-line hint + primary CTA) and apply it across Inbox, Decisions, Workflows, Automations, Sync Runs, Graph, Team. **Accept:** every list screen shows a consistent, branded empty state with a next-step CTA when it has no data.
- **SEV-204 — Loading states.** Data-fetching pages set state in `useEffect` with no skeleton/spinner, so they flash empty then populate. Add lightweight skeletons or spinners for Dashboard, Analytics, Integrations, Sync Runs, Team, Graph. **Accept:** no empty-flash before data arrives; a visible loading affordance.

### 4.2 Login / Onboarding
- **SEV-205 — Dead legal links.** `app/login/page.tsx` footer links Terms/Privacy to `href="#"`. Either add real pages or remove the links before public launch. **Accept:** legal links resolve or are removed.
- **SEV-206 — Demo login copy inconsistency.** `enterDemo()` sets org name "Intellact AI" then routes to `/demo`, which overwrites the same keys and routes to `/dashboard`; the two code paths duplicate the demo-session bootstrap. Consolidate to one place (`/demo`) to avoid drift. **Accept:** one demo-bootstrap code path.
- **SEV-207 — Onboarding "connect opens new tab" flow.** `app/onboarding/page.tsx::handleConnect` opens the Composio OAuth URL in a new tab and immediately marks the connector "connected" locally regardless of whether the user finished authorizing. This over-reports success. Reflect real connection state (poll `/integrations` or the Composio callback) instead of optimistic local marking. **Accept:** a connector shows connected only after the OAuth round-trip actually succeeds.

### 4.3 Ask OSAI
- **SEV-208 — Composer "mode" pills (Ask/Search/Take action) are cosmetic.** In `app/ask/page.tsx`, selecting a mode only changes the placeholder; all three submit the same `/ask` call. Either wire "Search" to `/search` and "Take action" to bias action-planning, or remove the pills to avoid implying capability that isn't there. **Accept:** modes either change behavior meaningfully or are removed.
- **SEV-209 — Citation confidence display.** Confidence is shown as a raw percentage (e.g. "75%") from cosine similarity; label it clearly (e.g. "relevance") so users don't read it as factual certainty. Minor copy change. **Accept:** confidence is labeled to avoid overclaiming.

### 4.4 Dashboard / Analytics
- **SEV-210 — Contradictory hero numbers (ties to SEV-104).** Once SEV-104 is resolved, ensure the Dashboard "Company Pulse" count, Analytics "Documents Indexed", and Sync Runs "Total in knowledge base" all read from the same source and agree. **Accept:** the three numbers match for a given workspace.
- **SEV-211 — Emoji connector icons.** Connectors are rendered with emoji (📝💬📁🎫📹) in Dashboard/Sync Runs. Fine for a demo; for production polish, replace with the real brand SVGs already implied by `lib/connector-meta.ts`/`CONNECTOR_META`. **Accept:** consistent icon system (not emoji) across connector surfaces.

### 4.5 Integrations
- **SEV-212 — Sync feedback copy leaks "demo mode".** `app/integrations/page.tsx::handleSync` catch block sets "Sync triggered (demo mode)" on any error, even for a real signed-in user whose sync genuinely failed. Show an honest error instead; only mention demo when `isDemo()`. **Accept:** real sync failures show a real error, not "(demo mode)".

### 4.6 Visual system
- **SEV-213 — Consistency pass.** Inline `style={{...}}` objects are mixed with utility classes and CSS-variable classes across pages (e.g. `sidebar.tsx`, `app-shell.tsx`, `login/page.tsx`). Consolidate repeated inline styles into classes; verify spacing/typography tokens are used consistently (the `docs/design-system.md` / `DESIGN.md` exist — reconcile against them). **Accept:** no ad-hoc inline color/spacing that duplicates an existing token; visual rhythm consistent across pages.

---

## 5. Code Quality & Performance

- **SEV-301 — In-memory proposed-action store won't survive multi-worker / restart.** `agent/orchestrator.py::_PROPOSED` is a per-process dict. With more than one web worker (or after a restart/cold-start), a proposed action created by one worker can't be confirmed by another → "Action not found or already handled." The code comment already flags this ("swap for a DB table when multi-worker"). On Render free (single instance) it mostly works but breaks on scale-out and on cold starts between propose and confirm. **Fix:** persist proposed actions in a `connector_actions` table keyed by id with `org_id`, `provider`, `tool`, `action`, `payload`, `status`, TTL; confirm reads from DB. This also enables the SEV-001 cross-org check on confirm. **Accept:** propose on one worker / confirm on another succeeds; restart between propose and confirm still allows confirm within TTL.

- **SEV-302 — Broad `except Exception` swallowing across the codebase.** Many best-effort `except Exception: pass` blocks (Composio overlay in `integrations.py`, ingest in `composio_ingest.py`, vector cleanup in `orgs.py`, memory in `orchestrator.py`, etc.). Several are legitimately best-effort, but they collectively hide real failures and make the "intermittent errors" hard to diagnose. **Fix:** ensure each swallowed exception is at least `logger.warning(...)`-logged with context (many already log; some just `pass`). Introduce structured logging and, for production, an error tracker (Sentry — deferred per notes but recommended before scale). **Accept:** no silent `except: pass` without a log line; a debugging pass can see why a sync/action failed.

- **SEV-303 — No structured logging / observability in production.** Logging is `logging.getLogger(...)` with default config; no request IDs, no Sentry/PostHog (explicitly deferred). Given the reported intermittent errors, this is the main reason they're hard to pin down. **Fix:** add a logging config (JSON logs, level via env), request/correlation IDs on the API, and wire Sentry (backend) once keys are available. **Accept:** production logs are queryable and errors are captured centrally.

- **SEV-304 — Embedding-dimension footgun.** `config.py` `embedding_dimension` defaults to 768 (Gemini) but the hash fallback provider is 64-dim; if Gemini is unset the collection dimension and the fallback vector length can diverge from what's already in Qdrant, silently degrading retrieval. The README documents "set 64 to use hash fallback." **Fix:** on startup, assert the active embedding provider's `dimension` matches the Qdrant collection's configured size; fail fast or recreate the collection with a clear message on mismatch. **Accept:** a dimension mismatch is detected at startup, not as silently-bad search results.

- **SEV-305 — N+1 external calls in ingestion (expected, but cap it).** `composio_ingest.py` fetchers loop per page/file/channel making a Composio call each (`_fetch_notion` fetches block contents per page, `_fetch_googledrive` downloads per file, `_fetch_slack` fetches history per channel). This is inherent to the APIs but is unbounded by wall-clock and runs on the web dyno (see SEV-005). **Fix:** enforce the `limit` consistently, add per-item timeouts, and (with the worker from SEV-005) parallelize with a bounded concurrency. **Accept:** ingestion of the max item count completes within a documented time bound and can't hang indefinitely.

- **SEV-306 — Frontend bundles all demo fixtures (`lib/demo-data.ts`, 786 lines) into the client.** The full demo dataset ships to every user, demo or not. Minor bundle bloat. **Fix:** dynamically import demo fixtures only when `isDemo()`, or code-split them. **Accept:** non-demo builds don't include the demo fixture payload (verify via bundle analysis).

- **SEV-307 — `test-file.md`, `test-file2.md`, `test-file3.md` committed at repo root.** Stray scratch files (`OSAI/test-file*.md`). Remove. **Accept:** repo root has no stray test scratch files.

- **SEV-308 — Resolved by disablement.** The Zoom route is now an unconditional hidden 404, its capability is false, mock/download/transcription worker behavior was removed, and legacy Zoom env vars cannot enable it or block startup. A future Zoom integration still requires tenant-bound OAuth/webhook authentication and live contract tests before reintroduction.

---

## 6. Deployment Readiness Checklist

| # | Item | Status | Action |
|---|---|---|---|
| D1 | **Secrets management** | Partial | `render.yaml` marks keys `sync: false` (good). Verify all are actually set in the live Render env, especially `OSAI_JWT_SECRET` (SEV-002). Confirm no secret is committed (`.env` is gitignored; `git ls-files` shows only `.env.example` — good). |
| D2 | **Tenant isolation** | ❌ Blocked | SEV-001, SEV-101, SEV-102 must be closed before a second real customer. |
| D3 | **JWT secret guard** | ❌ | SEV-002 — refuse to boot insecurely in prod. |
| D4 | **Async worker** | Partial | A paid worker, beat, routed scheduler heartbeat, and recurring automation execution are defined. SEV-005 remains for real ingestion offload, retry/backlog visibility, and deployed proof. |
| D5 | **CORS** | OK-ish | `api/main.py` uses `allow_origins=settings.allowed_origin_list` with `allow_credentials=True` — good (not wildcard). Ensure `OSAI_ALLOWED_ORIGINS` is set to the exact Vercel URL in prod (no trailing slash). |
| D6 | **Error boundaries + 404** | ❌ | SEV-105. |
| D7 | **Health check** | OK | `/health` exists and Render `healthCheckPath: /health` is wired. |
| D8 | **DB migrations on boot** | OK | Dockerfile runs `alembic upgrade head` then idempotent seed. Verify the prod seed does NOT seed demo content into real orgs (per project notes `provision_org` no longer seeds demo data — confirm current code). |
| D9 | **Observability** | ❌ | SEV-303 — no Sentry/structured logs. Recommended before scaling; document as known gap for pilot. |
| D10 | **Rate limiting** | ❌ | SEV-101/102 — none on `/orgs`, `/auth/login`, `/ask`. |
| D11 | **CI** | Partial | `.github/workflows/ci.yml` runs ruff + pytest on backend PRs against real PG/Qdrant/Redis. **No** frontend CI (no `tsc`/lint/build gate on `osai-web`). Add a frontend job. Also the suite is currently red (SEV-108). |
| D12 | **Frontend build config** | OK | `vercel.json` + `next.config.ts` present; API proxied via `NEXT_PUBLIC_API_BASE_URL`. Fix demo env var names (SEV-106) and redirect targets (SEV-107). |
| D13 | **Cold-start UX** | Handled | Free Render web cold-starts are mitigated in-app (login retries `/auth/config` 3×, longer timeouts). Document the first-load delay; consider a paid instance for demos. |
| D14 | **Submodules** | Check | `services/gbrain` and `services/hermes` are git submodules. Ensure the prod OSAI-API build doesn't require them and `git submodule update --init` is documented (README covers gbrain). |
| D16 | **Hermes sidecar (launch-critical)** | ❌ | SEV-401 — confirmed in scope for launch. Must be deployed (paid Render Docker service + persistent disk at `/data/hermes`), pass the `services/hermes-sidecar/DEPLOY.md` step-4 gate, be wired via `OSAI_HERMES_SIDECAR_URL`, and have monitoring on the `via` field so a silent fallback to the in-house agent is caught. Depends on SEV-001. Not yet run end-to-end. |
| D15 | **Zoom integration** | Disabled | SEV-308 is closed by a hard 404. Keep unavailable until a tenant-bound authenticated design is implemented and tested. |
| D17 | **Database (Supabase)** | Partial | Postgres migrated from Render to Supabase. `OSAI_DATABASE_URL` is now a dashboard secret (URL-encode the password: `@`→`%40`, `!`→`%21`; append `?sslmode=require`). Alembic DSN `%`-escape fix is in `db/migrations/env.py`. **Free-tier Supabase pauses after ~7 days idle** — before launch, upgrade to a paid plan or add a keep-alive ping (e.g. a scheduled hit to `/health` that runs a trivial query) so the pilot API doesn't silently go down. Retire the old Render Postgres (delete the `databases:` block in `render.yaml`) once the deployed app is verified against Supabase and pilot data is confirmed migrated. |

---

## 6b. Unbuilt / Blocked Goals to Complete (from plan docs & pilot notes)

These were planned but not finished, and the user explicitly asked to fold remaining goals into this plan. Verify current state against code before building (some may be partially done since the notes were written).

- **SEV-401 — Hermes per-user agent sidecar: IN SCOPE FOR LAUNCH — deploy, wire into the primary flow, validate, and monitor.**
  - **Decision (confirmed by product):** Hermes is the per-user reasoning runtime for launch, not optional/additive. This upgrades it from "nice-to-have, off by default" to a **launch-critical, must-validate** item. It is a substantial workstream — treat it as its own phase.
  - **Current state (verified):** The OSAI side of the seam is fully built and correct: `agent/hermes_client.py` retrieves the user's *permission-scoped* org context (via `retrieve_answer(..., requester_permissions=...)`, so the permission boundary stays in OSAI) and POSTs `{prompt, org_id, user_id, permissions}` to `{OSAI_HERMES_SIDECAR_URL}/run`. The sidecar service exists at `services/hermes-sidecar/` (`main.py` FastAPI wrapper, `Dockerfile` that installs the hermes CLI, `docker-compose.yml`, and a step-by-step `DEPLOY.md` runbook). It is **inert** unless `OSAI_HERMES_SIDECAR_URL` is set, and it has **never been run end-to-end** — `DEPLOY.md` step 4 (a real `/run` returning `{"result": "<text>"}`) is the validation gate that has never passed.
  - **Gap 1 — Hermes is only wired into Automations, not the primary Ask flow.** `api/routes/automations.py::run_` calls `run_via_hermes(...)` and falls back to `run_ask(...)`. But the main user surface — `POST /ask` → `agent/orchestrator.py::run_ask` — **never calls Hermes**; it always uses the in-house RAG orchestrator. If Hermes is *the* launch reasoning runtime, the Ask page (the product's headline feature) currently bypasses it entirely. **Decide and implement the intended topology:** either (a) route `/ask` through Hermes too (inject permission-scoped context, call the sidecar, keep OSAI's propose/confirm **action** layer in front so approvals still happen in OSAI — Hermes returns text only via `hermes -z`), or (b) consciously scope Hermes to Automations for launch and document that Ask stays on the in-house agent. Do not "launch on Hermes" while the main surface silently doesn't use it.
  - **Gap 2 — silent fallback hides whether Hermes is actually running.** By design, `run_via_hermes` returns `None` on any sidecar error and the caller falls back to the in-house agent, surfacing `via: "osai"` in the response. This is the correct *safety* behavior, but when Hermes is launch-critical it becomes a **monitoring blind spot**: you can ship "with Hermes" and unknowingly serve the in-house agent to every user because the sidecar is down/misconfigured. **Add observability:** log + emit a metric on every run's `via` value; alert when the Hermes-configured environment falls back to `osai` above a threshold. Surface the `via`/route in the response so the app (and evals) can assert Hermes actually ran.
  - **Action / deploy steps (follow `services/hermes-sidecar/DEPLOY.md`):**
    1. Pick a provider + model (runbook §0 — OpenRouter easiest): set `OPENROUTER_API_KEY`, `HERMES_MODEL`, `HERMES_PROVIDER`. **Note the model IDs in that runbook (`anthropic/claude-sonnet-4`) are stale** — use current Claude model IDs (e.g. Opus 4.8 / Sonnet 5 / Haiku 4.5) per the exact IDs available on your provider; verify the provider's model list before hardcoding.
    2. Validate locally first (runbook §1): `docker compose up --build` in `services/hermes-sidecar`, then `curl /health` and `curl -X POST /run` — must return a real `{"result": ...}`.
    3. Deploy the sidecar as a **Docker Web Service on a paid Render instance** (the image installs the hermes CLI and runs `hermes -z` via `subprocess.run` with a 180s timeout — this needs real CPU/RAM and time; free tier will not cut it). Root dir `services/hermes-sidecar`, health check `/health`.
    4. **Attach a persistent disk mounted at `/data/hermes`** — for a real multi-tenant launch (not just a pilot), per-user Hermes memory/skills must survive restarts and redeploys. The runbook marks this "optional / fine for pilot"; for launch it is **required**, otherwise every redeploy wipes all users' agent memory.
    5. Pass the `DEPLOY.md` step-4 gate against the deployed URL (a real `/run` result). **Do not wire OSAI until this passes.**
    6. Set `OSAI_HERMES_SIDECAR_URL` on the `osai-api` service; validate end-to-end (runbook §6) that responses carry `via: "hermes"`, not `via: "osai"`.
  - **Concurrency / scale caveat to resolve before launch:** the sidecar runs `subprocess.run(hermes -z ...)` synchronously per request. Under concurrent users this blocks a worker per run for up to 180s and spawns a CLI process each time. Load-test realistic concurrency; add a concurrency limit / queue, size the instance, and consider multiple sidecar workers. This is the main scaling risk of the current design.
  - **Security note (must hold):** the isolation guarantee is that OSAI injects only permission-scoped context and enforces the boundary on its side — this depends on SEV-001 being fixed first (today `/search`/`/ask` ignore permissions, so the context OSAI would feed Hermes is *not* actually permission-filtered for a non-admin). **Do SEV-001 before relying on Hermes isolation.**
  - **Rollback:** unset `OSAI_HERMES_SIDECAR_URL` on `osai-api` and redeploy → instant return to the in-house agent, no data migration.
- **`[INFERRED]` labels for SEV-401:** the runbook model IDs, the free-tier-insufficiency, and the concurrency behavior are reasoned from the code + Render constraints; validate against the live deploy.
- **SEV-402 — Cross-department "collaboration" surfacing.** Planned: group the access map by department and add a department filter to the Decision Log; `build_access_graph` should return each user's department. **Action:** verify `graph/provider.py::build_access_graph` returns department, group the Org Graph matrix by department (the UI already shows an "UNASSIGNED" group header, so partial), and add the Decision Log department filter.
- **SEV-403 — Broader one-click Composio connectors.** Planned: surface Gmail/Calendar/Outlook as one-click cards. Ingestion fetchers today exist only for `notion`, `googledrive`, `slack` (`composio_ingest.py::_FETCHERS`); other toolkits can connect via OAuth but won't ingest. **Action:** either add fetchers for the additional toolkits or clearly label connect-only apps as "actions only, no ingestion yet" so users aren't misled.
- **SEV-404 — Media transcription for Drive audio/video at scale.** Whisper transcription exists (`composio_ingest.py::_transcribe_media`, Groq free tier) but is capped at 25MB and runs on the web dyno. **Action:** tie into the worker (SEV-005) and handle larger media (chunking or size messaging) so real meeting recordings ingest reliably.
- **SEV-405 — Freshdesk native ingestion.** `_FETCHERS` has no `freshdesk` entry and the native Freshdesk connector's real ingestion path should be confirmed. **Action:** verify Freshdesk actually ingests (the dashboard demo shows 47 Freshdesk docs, but that's demo data) or label it connect/action-only.

---

## 7. Suggested Execution Order

Work top-to-bottom. Each phase should end green (`ruff`, `pytest`, `tsc`, app boots) before starting the next.

### Phase 1 — Security blockers (do first, ~1–1.5 days)
1. **SEV-001** — Apply `get_org_id` + per-user permissions to `/search`, `/ask`, `/ask/actions/confirm`, `/workflows` POST, and the workflow-approve endpoint; ignore body `org_id`. *(This is the headline fix.)*
2. **SEV-002** — JWT secret startup guard for non-local env.
3. **SEV-102** — Gate password-less `/auth/login` to local/demo; make Google OAuth the prod auth path.
4. **SEV-101** — Rate-limit + validate `/orgs` and `/auth/login`.
5. **SEV-308** — Closed by hard-disablement; do not re-enable the legacy route.
6. **SEV-108** — Fix the stale auth test; get the suite green. Add a cross-org isolation regression test.
> **Gate:** unauthenticated probes to the five endpoints return 401; cross-org body `org_id` is ignored; `pytest` all green.

### Phase 2 — Integration/reliability blockers (~1 day)
7. **SEV-003** — Stop fabricating fake "executed" actions in the Ask UI (non-demo).
8. **SEV-005** — Ingestion reliability: hard caps + guaranteed terminal `SyncRun` status now; plan/enable the Celery worker for real async.
9. **SEV-301** — Persist proposed actions in a DB table (also strengthens SEV-001 confirm check).
10. **SEV-304** — Embedding-dimension startup assertion.
11. **SEV-104** — Fix demo-fixture bleed into real workspaces (separate the seeded admin from `demo-org`; make per-mode numbers consistent).
> **Gate:** a real sync completes or fails cleanly with a visible status; approve/confirm works across restart; real vs demo numbers are self-consistent.

### Phase 3 — UI/UX overhaul (~2–3 days)
12. **SEV-004** — Mobile/responsive layout (sidebar drawer + stacking).
13. **SEV-105** — Error/404/loading boundaries.
14. **SEV-103** — Honest LIVE badge.
15. **SEV-203 / SEV-204** — Reusable empty + loading states across all list screens.
16. **SEV-202 / SEV-210 / SEV-211 / SEV-212 / SEV-213** — Overflow fixes, number consistency, icon system, honest sync copy, visual-consistency pass.
17. **SEV-201 / SEV-205 / SEV-206 / SEV-207 / SEV-208 / SEV-209** — Dead Export button, legal links, demo path consolidation, honest onboarding connection state, Ask mode pills, confidence labeling.
> **Gate:** every core screen looks intentional at 375/768/1280px, with consistent empty/loading/error states and no dead controls.

### Phase 4 — Config, cleanup, hardening (~1 day)
18. **SEV-106 / SEV-107** — Env-var name reconciliation; redirect-target cleanup.
19. **SEV-302 / SEV-303** — Log all swallowed exceptions; add structured logging + (when keys available) Sentry.
20. **SEV-306 / SEV-307** — Code-split demo fixtures; remove stray `test-file*.md`.
21. **D11** — Add frontend CI (typecheck + build) alongside backend CI.
> **Gate:** `.env.example` matches code; no silent `except: pass`; frontend has a CI gate; clean repo.

### Phase 5 — Hermes reasoning runtime (LAUNCH-CRITICAL — confirmed in scope, ~2–3 days)
> Sequence **after Phase 1** (SEV-001 is a hard prerequisite — the permission-scoped context Hermes relies on isn't actually filtered until SEV-001 lands) and ideally after Phase 2 (the DB-backed action store, SEV-301, matters if `/ask` routes through Hermes while keeping OSAI's approval layer). Can run in parallel with Phase 3/4 UI work.
22. **SEV-401** — Deploy the Hermes sidecar (paid Render Docker service + persistent disk), pass the `DEPLOY.md` step-4 real-`/run` gate, decide + implement the topology (route `/ask` through Hermes vs. scope to Automations), wire `OSAI_HERMES_SIDECAR_URL`, add `via`-field monitoring/alerting on silent fallback, and load-test the synchronous `subprocess` concurrency model.
> **Gate:** a real user request returns `via: "hermes"` (not `osai`) end-to-end; per-user memory persists across a redeploy; non-admin users only ever have permission-scoped context reach Hermes; falling back to the in-house agent raises a visible alert; rollback (unset one env var) verified.

### Phase 6 — Remaining unbuilt goals (sequence after launch-critical work)
23. **SEV-402 / SEV-403 / SEV-404 / SEV-405** — Department collaboration surfacing, more connectors, media at scale, Freshdesk ingestion.

---

## Appendix A — What was verified live vs. inferred

**Reproduced against the running app/API:**
- Unauthenticated `/search`, `/ask`, `/workflows` (POST) returning data / 200 with arbitrary body `org_id` (SEV-001).
- Guarded routes (`/dashboard/metrics`, etc.) returning 401 without auth.
- `/orgs` creating an org unauthenticated (SEV-101).
- Broken mobile layout at 375px (screenshot).
- Contradictory demo/real numbers on Dashboard vs Analytics vs Sync Runs for the seeded `demo-org` admin (SEV-104, SEV-210).
- Hardcoded "LIVE / actively syncing" badge with 0 connectors (SEV-103).
- Absent `error.tsx`/`not-found.tsx`/`loading.tsx` (SEV-105).
- Demo env-var name mismatch and unused `NEXT_PUBLIC_DEFAULT_ORG_ID` (SEV-106).
- `pytest`: 50 passed / 1 failed (stale auth test) / 2 skipped; `ruff` clean; `tsc` clean.
- Ask, Integrations, Sync Runs, Analytics, Team, Workflows, Settings, Org Graph all render on desktop.

**Inferred from code (labeled `[INFERRED]` above) — verify before acting:**
- SEV-005 OOM/timeout behavior under real load (reasoned from free-tier constraints + commit history + the media size guards).
- SEV-107 redirect-target staleness (reasoned from IA notes vs. existing pages).
- SEV-003 non-demo fabrication path (read in code; not triggered live, but the missing `isDemo()` guard is unambiguous in `app/ask/page.tsx`).

## Appendix B — Notable things done *right* (don't rebreak)
- `get_org_id` correctly refuses client-supplied `X-Org-Id` except for the public `demo-org`, and derives org from the verified JWT — the right pattern; it just needs to be applied to the leaky routes.
- Google OAuth flow (`auth.py`) is solid: JWKS signature verification, audience/issuer checks, `email_verified` check, CSRF state cookie, token passed via URL fragment (not query) so it stays out of server logs.
- `lib/api.ts` bounds every request with a timeout and resolves to safe fallbacks — good resilience against a slow/cold backend.
- Retrieval has an honest relevance floor (`retrieval_min_score`) and a non-hallucinating fallback answer when the LLM is unavailable.
- LLM generation retries on 429/5xx with backoff honoring `Retry-After`.
- Secrets are gitignored; `render.yaml` uses `sync: false` for all sensitive envs.
