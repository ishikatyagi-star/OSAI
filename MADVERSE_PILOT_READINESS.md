# Madverse Pilot Readiness Audit — 2026-07-20

Scope: everything a Madverse user can touch, judged from their side of the screen.
Method: re-verified every finding of the 2026-07-12 audit against today's `main`
(post PR #176), plus a fresh pass over the failure surfaces that caused this
month's incidents (integration syncs, Ask, cold starts, scheduling). Bias check:
findings are stated against *user-visible behavior*, not code aesthetics — several
things the codebase does "correctly" are still failures from the pilot's
perspective and are listed as such.

Verdict up front: **the security/tenancy core is genuinely solid; the reliability
envelope around it is not pilot-proof yet.** There are 4 pilot-breakers (P0),
all fixable in ~2–3 focused days, mostly with boring, proven open-source tooling
rather than new code.

---

## 1. What is verified solid (do not spend more time here)

- **Tenant isolation**: org always from verified JWT; body/header spoofing rejected
  (re-verified in the July 12 audit with live probes; the test suite covers it).
- **Security hardening stack** (PRs #146–#153): fail-closed webhook + sidecar auth,
  httpOnly session cookie, JWT revocation, demo-write 403 matrix, CSP headers.
  Config guards refuse to boot misconfigured prod. This is better than most pilots ship with.
- **Approval model**: destructive actions are propose → approve, single-consume,
  approver-bound, cross-org guarded.
- **CI**: backend + web CI both green on main; brand-copy guard enforced.
- **Ingestion memory safety**: download caps, per-doc embedding yield, OOM guards
  (PRs #170–#173) — the 512MB instance no longer dies mid-sync.
- **July 12 audit blockers since fixed**: inbox shell removed, demo-only dashboard
  block removed, data-routing dead redirect removed, Zoom webhook fail-closed +
  feature-flagged, web tests all running in CI, Gmail fetcher + catalog-connector
  sync 404s (PR #175).

## 2. P0 — will break the pilot in week one

### P0-1 · Scheduled automations still never fire in prod
The UI sells hourly/daily/weekly cadences; nothing executes them. Celery beat is
the only trigger and render.yaml deploys no worker (free tier). A Madverse user
who sets up "chase open escalations every morning" gets silence — the exact
"dead-end automation" complaint, shipped again.
**Fix (pick one, ship this week):**
- *Free, 1–2h:* GitHub Actions cron (the keep-alive pattern already proven in this
  repo) POSTs an authed `/internal/automations/run-due` endpoint every 15 min.
  Endpoint already exists as a Celery task body (`run_due_automations`) — expose it
  behind a shared-secret header.
- *Cleaner, $7/mo:* deploy the Celery worker+beat as a Render worker service.
**Also:** until fixed, the cadence dropdown must say "runs when triggered manually"
— never sell a cadence that doesn't run.

### P0-2 · One component crash blanks the whole app
There is **no `error.tsx` / `global-error.tsx`** anywhere in osai-web. Any render
error on any page = white screen, no recovery, no message. This is the single
cheapest robustness win available: Next.js has first-class error boundaries built in.
**Fix:** root `global-error.tsx` + `error.tsx` with a branded "something went wrong,
retry" card; per-route boundary for Ask (the highest-traffic surface). ~2h.

### P0-3 · Zero error visibility — you find out from Yash's screenshots
No Sentry, no error tracking, backend or frontend. Every incident this month was
discovered by a human tripping over it. `apiGet` deliberately swallows failures
into fallbacks (only a `console.warn`), so a dying backend renders as an *empty
workspace* — indistinguishable from "no data yet" to both the user and you.
**Fix:**
- **Sentry** (free tier: 5k errors/mo, both SDKs) or self-hosted **GlitchTip**
  (Sentry-API-compatible, lighter). Backend: `sentry-sdk[fastapi]`, one init line.
  Frontend: `@sentry/nextjs`, wraps the error boundaries from P0-2 automatically.
- **UptimeRobot** (free) or **openstatus** (OSS) pinging `/health/ready` with a
  Slack/email alert — you learn the API is down before Madverse does.
- Give `apiGet` failures a visible state on the three pilot-critical pages
  (Ask, Integrations, Dashboard): "Couldn't reach Sheldon — retrying" instead of
  silently empty. The Integrations page already has this pattern (`loadError`);
  copy it, don't invent.

### P0-4 · Free-tier compute is the root cause of half the "random" errors
0.15 vCPU / 512MB / ~15-min idle spin-down. Cold starts are 30–60s; the keep-alive
cron only covers 02:00–19:00 UTC and GitHub delays/disables scheduled workflows
under load (documented in the workflow file itself). Syncs, embeddings, and Ask
share one starved process. Most of the "too many roadblocks, errors in each
integration" experience is this instance, not the code.
**Fix:** pay the $7/mo for Starter on `osai-api` for the pilot's duration
(always-on, 0.5 vCPU/512MB, no cold starts) and ideally the same for the worker
(P0-1). ~$14/mo total buys away an entire class of intermittent failure. This is
the highest-leverage reliability change on this list and it isn't code.

## 3. P1 — trust erosion (fix before pilot, days not weeks)

- **P1-1 · No retries on external calls.** Composio, embeddings, LLM: every call is
  one `httpx` attempt with a timeout. One network blip = one failed sync/answer.
  Add **tenacity** (OSS, standard) — 3 attempts, exponential backoff + jitter,
  retry only on timeout/5xx/connection errors, on: Composio execute/list calls,
  embedding calls, LLM calls. ~half a day including tests.
- **P1-2 · Gmail + live-read paths unverified against real Composio.** Parsing is
  defensive but shape-checked only against mocks (PR #175). Run one real
  connect→sync→Ask pass for Gmail, Drive, Notion, Slack, Freshdesk in a scratch
  workspace before Madverse does. Record results in the smoke checklist.
- **P1-3 · No end-to-end smoke suite.** The golden path (sign in → connect →
  sync → ask → get cited answer → approve action) exists only as a manual
  checklist. Add **Playwright** (OSS): one spec covering that path against a local
  stack, run in CI nightly + pre-deploy. This is the "final test" automated — it
  catches the class of regression Yash keeps finding by hand. 1 day.
- **P1-4 · Cadence/UX honesty sweep.** Anything visible that doesn't work in prod
  must be hidden or labeled. Known: automation cadences (P0-1). Sweep for others:
  demo-only affordances leaking into real-org views. (The July UX pass caught most;
  do one final pass with a real org, not demo.)
- **P1-5 · Supabase session-pooler behavior under load is unproven.**
  `pool_pre_ping` is set (good); transaction-mode pooler + SQLAlchemy defaults are
  fine at pilot scale, but set an explicit `statement_timeout` (e.g. 15s) via
  engine connect args so one bad query can't wedge the only web process.

## 4. P2 — polish (post-pilot-start, opportunistic)

- Dead code from the July 12 audit still present (orphaned components, `llm/router.py`,
  unused endpoints) — harmless, defer.
- SQL DSNs plaintext at rest — acceptable at pilot, flag for launch (unchanged).
- `/dashboards` vs `/dashboard` naming confusion (unchanged).
- Live-read v1 limits: literal app-name matching, one app per question — fine to
  ship, document in Ask's empty-state hints ("mention the app by name").

## 5. Open-source stack summary (all boring, all proven)

| Gap | Tool | License/cost | Effort |
|---|---|---|---|
| Error tracking | Sentry SDKs (or GlitchTip self-host) | free tier / OSS | 2h |
| Crash containment | Next.js error boundaries (built-in) | — | 2h |
| Uptime + alerting | UptimeRobot or openstatus | free / OSS | 30min |
| Retries | tenacity | MIT | 0.5d |
| Scheduling w/o worker | GH Actions cron → authed endpoint | free | 2h |
| E2E smoke | Playwright | Apache-2 | 1d |
| Cron-didn't-run alerts | healthchecks.io | free/OSS | 30min |
| Always-on compute | Render Starter ×2 | $14/mo | 0 |

Deliberately **not** recommended: Temporal/Airflow (massive overkill at this
scale), LiteLLM (routing already handled in `llm/policy.py`), replacing any
existing layer. The plane you built is the right shape; it needs an error
budget, not a rewrite.

## 6. Suggested order (2–3 days)

1. **Day 0 (no code):** Render Starter upgrade · UptimeRobot on `/health/ready` ·
   Sentry projects created.
2. **Day 1:** error boundaries + Sentry SDKs + visible error states on Ask/
   Integrations/Dashboard · automations honesty copy.
3. **Day 2:** GH-cron scheduler for automations (or worker deploy) · tenacity on
   Composio/embeddings/LLM calls.
4. **Day 3:** Playwright golden-path spec · real-Composio verification pass of all
   five connectors (P1-2) · run the full SMOKE_TEST_CHECKLIST against prod.

Exit criterion for "fool-proof enough": the Playwright golden path passes against
prod, UptimeRobot shows 24h green, Sentry shows zero unexpected errors over a
48h window with you and Yash using it daily, and a scheduled automation fires
on time twice without human help.
