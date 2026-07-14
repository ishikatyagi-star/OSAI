# Sheldon frontend UI remediation and backend handoff

Date: 2026-07-14

## Scope and boundary

This pass implements the frontend findings from the deployed UI/UX audit. All product changes are inside `osai-web`. No backend service, database schema, migration, worker, deployment, or server-side business rule was changed.

`osai-web/lib/api.ts` was updated only as the browser-side API client: requests now time out consistently and selected reads can reject into honest UI error states. It does not change any backend endpoint or payload.

## Frontend changes completed

### Shared application shell and responsive behavior

- Replaced the desktop-only sidebar behavior with an accessible mobile drawer at 900px and below. The drawer has a labelled dialog, focus containment, a close control, and the full primary navigation.
- Added Settings to the persistent navigation and improved labels for the home link, primary navigation, profile summary, and mobile trigger.
- Changed the workspace badge from the misleading `LIVE` label to `DEMO` for the sample workspace. Added a persistent demo banner and an explicit Exit demo action.
- Kept public/auth pages outside the authenticated application shell so login, onboarding, callback, and demo transitions do not inherit workspace navigation.
- Normalized interactive targets to at least 44px where the audit found cramped controls.
- Added responsive wrapping and stacking for page headers, cards, forms, actions, and statistics. Dashboard statistics render as one column at 375px.

### Tables, cells, and spacing

- Standardized data-table header and body cells to `12px 16px` padding.
- Added dedicated horizontal scroll containers instead of allowing tables to widen the document.
- Added stable table minimum widths and a sticky first column where retaining row identity matters on narrow screens.
- Removed arbitrary per-page cell padding that caused column and row misalignment.
- Mobile browser measurement on Team: document overflow `0px`, table viewport `326px`, table content `713px`, header padding `12px 16px`, cell padding `12px 16px`.

### Honest loading, empty, error, and mutation states

- Added strict read/error handling to Analytics, Decisions, Wiki, Artifacts, Graph, Team, Integrations, Sync Runs, Evals, SQL, and workflow details. A failed backend request no longer appears as a legitimate empty workspace or a zero metric.
- Preserved partial data when an ancillary request fails. Examples: members still render if invites fail; integrations still render if metrics or sync history fail; sync runs still render if summary metrics fail.
- Added retry actions and local error messages for load and mutation failures.
- Added bounded timeouts to GET, POST, PATCH, and DELETE requests in the frontend API client.
- Awaited destructive and approval mutations before changing the interface. Failed operations retain the original item and explain that no change occurred.
- Moved errors into their relevant dialogs where global page errors were previously easy to miss.

### Demo safety and consistency

- Centralized shared demo statistics, integrations, teams, departments, documents, decisions, workflow runs, and automations so numbers agree across pages.
- Ask, Analytics, Team, Graph, Automations, Integrations, Sync Runs, and workflow details now use local demo data for the sample journey.
- Demo transcript extraction and approval branch before mutation calls, so they cannot reach real workflow endpoints.
- Demo integration sync is labelled as a preview and never claims that an external source changed.
- Connector management opens immediately with explicit sample health/file messaging; it does not wait on live connector endpoints in demo mode.
- Disabled external connector, account deletion, reset, and Slack setup operations in the shared demo.
- Added operation locking and confirmation dialogs to prevent overlapping Run, edit, token, revoke, and delete actions for one automation.

### Page and flow improvements

| Area | Completed frontend improvements |
|---|---|
| Landing, SaaS, Universities | Made Try a Demo the primary product CTA, clarified positioning copy, added mobile navigation, reduced-motion support, honest contact messaging, correct canonical metadata, and direct booking links. Removed the 3.5 MB inline university hero image; the page HTML is now about 32 KB. Fixed the 375px university header collision and cache-busted the shared CSS. |
| Login, onboarding, auth callback | Removed duplicate loading/config work, added pending states and form labels/autocomplete, used client navigation, and replaced the timed callback dead-end with branded retry/recovery actions. |
| Dashboard, Ask, Analytics | Aligned all demo counts, added Search mode routing, stopped demo API calls, and distinguished unavailable metrics from zero metrics. |
| Decisions, Wiki, Artifacts | Added load/mutation errors, retry behavior, confirmations, accessible sorting, and non-optimistic destructive actions. |
| SQL | Added labelled credentials, password reveal, safer generic error copy, delete confirmation, and responsive result tables. |
| Team and Graph | Added semantic tabs/tables, keyboard arrow navigation, form labels, tier fallbacks, resilient partial loads, and mobile scrolling. |
| Automations and workflow detail | Added local demo fixtures, scheduler-required copy for unsupported cadence, named confirmations, per-item mutation locks, honest run failures, keyboard tabs, and approval review before external execution. |
| Integrations and Sync Runs | Added independent metrics/history/health/document states, stale-request guards, local demo behavior, clear connector restrictions, accessible progress, and preserved primary data when secondary requests fail. |
| Settings and Evals | Corrected destinations, added typed confirmation for reset/delete, kept sessions intact after failed deletion, scoped reset language, and routed Advanced settings to the canonical Evals page. |
| Legacy routes | Preserved user intent: Context Inbox to Ask, Data Routing to Team, Decision Log to Decisions, Team Board to Decisions, Org Graph to Graph, Workflows to Automations, Search to Ask Search mode, Dashboards to Analytics, and Board to Decisions. |

## Browser and build verification

The final verification ran against a production Next.js build through the in-app browser.

- `npm.cmd test`: 20/20 tests passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run build`: passed; 27 routes generated, including the dynamic workflow route.
- `git diff --check -- osai-web`: no whitespace errors (only Windows line-ending notices).
- Desktop: 1280x720.
- Tablet: 768x1024; mobile drawer active, no document overflow, wide decision table contained in its scroll region.
- Mobile: 375x812; mobile drawer active, sidebar hidden, one-column dashboard statistics, no document overflow.
- The landing hero's Try a Demo control was clicked in the browser and completed at `/dashboard` with the `DEMO` badge, demo banner, and consistent sample counts.
- All audited routes and legacy redirects were revisited. No unexplained route gap remained.
- Automation tabs were exercised by keyboard; ArrowRight moved selection and focus from Run a task to From transcript.
- Demo transcript extraction produced a local fifth run with no alert or API-dependent failure.
- Automation edit locking and delete confirmation were exercised; the destructive action was cancelled.
- A connector manager was opened in demo mode; sample status/files appeared immediately with no loading spinner or alert.
- Fresh production browser tab: no console errors.

### Screenshot evidence

- [Landing desktop](./ui-audit-screenshots/landing-desktop.png)
- [Demo dashboard desktop](./ui-audit-screenshots/demo-dashboard-desktop.png)
- [Demo dashboard mobile](./ui-audit-screenshots/demo-dashboard-mobile.png)
- [Team table and cell padding on mobile](./ui-audit-screenshots/team-table-mobile.png)
- [Universities header and hero on mobile](./ui-audit-screenshots/universities-mobile.png)

## Backend handoff: work still pending

These items were intentionally not implemented in this frontend-only pass. The backend owner should confirm the current server state and implement any missing contract below.

### P0: required for safe production behavior

| Item | Backend change | Suggested contract / acceptance criteria |
|---|---|---|
| Deployment readiness | Add explicit liveness, readiness, and capability reporting; verify CORS, environment validation, migrations, and required workers at startup. | `GET /health/live`, `GET /health/ready`, and `GET /capabilities`. Readiness must fail when required storage/migrations are unavailable. Capabilities must state scheduler, connector, SQL, and workflow-execution availability. |
| Authentication and sessions | Replace URL-fragment/localStorage bearer-session dependence with a one-time callback exchange or HttpOnly session cookie. Add logout/session introspection and enforce OAuth state, PKCE, expiry, and replay protection. | `POST /auth/exchange`, `GET /auth/session`, `POST /auth/logout`; cookies `HttpOnly`, `Secure`, and appropriate `SameSite`. Callback codes must be single-use. |
| Demo isolation | Enforce demo read-only behavior centrally, not only in React. Reject every write and external side effect for demo identities. | Mutations return `403` with a typed code such as `DEMO_READ_ONLY`. Optional preview endpoints must be non-persisting. Tests must prove demo cannot sync, invite, reset, delete, execute SQL, or execute workflow actions. |
| Workflow approvals | Persist the requested action before execution, check permissions, use idempotency keys, and expose an explicit state machine with durable failures and an audit trail. | States should distinguish `needs_review`, `approved`, `executing`, `completed`, `failed`, and `cancelled`. Duplicate approval requests must not execute twice. |
| SQL safety | Enforce admin authorization, encrypted connection secrets or secret references, TLS/read-only database roles, egress/SSRF restrictions, query parsing, server-side read-only enforcement, rate limits, and audit records. | The backend must reject writes even if the UI is bypassed. Never return stored DSN passwords. Log actor, connection, query fingerprint, duration, and outcome. |
| University interest/contact | Add a durable, rate-limited endpoint before enabling a message form. Include validation, idempotency, spam controls, and an accepted/persisted response. | `POST /contact/university-interest`; return success only after durable acceptance. Until then the frontend correctly directs users to booking. |

### P1: required for complete product behavior

| Item | Backend change | Suggested contract / acceptance criteria |
|---|---|---|
| Integrations and sync | Sign and validate OAuth state, move syncs to a durable queue, return a run ID, expose polling states, and define disconnect/revocation behavior. | Sync trigger returns `202 { sync_run_id }`; the run progresses through queued/running/succeeded/failed with timestamps and error codes. Disconnect revokes credentials and records cleanup status. |
| Scheduler and automations | Deploy the scheduler/worker path, publish supported cadences through capabilities, use leases/idempotency, and persist attempts/retries. | Reject unsupported cadence values instead of accepting a schedule that will never run. Every attempt has a durable run record. |
| RBAC and invites | Centralize permissions for roles, invites, departments, data tiers, integrations, resets, and destructive actions. Validate enums and protect the last admin. | Invite tokens are hashed, one-time, expiring, revocable, and resendable. The backend rejects last-admin demotion/removal. |
| Destructive operations | Require recent reauthentication for account/org deletion and sensitive reset. Define reset scope and return operation IDs for long-running work. | Async operations expose progress and partial failure. Ownership and last-admin constraints are enforced server-side. |
| Metrics semantics | Do not convert database/service failures to zero. Define each count and include freshness metadata. | Metrics response includes `as_of`; unavailable dimensions return a typed unavailable/error state. Dashboard, Analytics, Integrations, and Sync Runs reconcile to the same definitions. |
| Deployment drift | Add post-deploy checks for route/API version compatibility, migrations, workers, and required environment variables. | A deployment is not healthy until web, API, storage, migrations, and required workers report the expected release/version. |

## Frontend follow-up after backend contracts land

The current frontend is safe and honest with the existing contracts. A later integration pass should:

1. Migrate the browser to the new session/exchange contract and consume server-provided permissions.
2. Map typed backend error codes to specific recovery copy.
3. Poll returned sync/reset/destructive operation IDs rather than relying on generic completion messages.
4. Enable recurring cadence choices from `/capabilities` instead of static assumptions.
5. Render the complete workflow approval state machine and durable audit events.
6. Replace direct SQL password handling with a one-time secret/reference flow.
7. Enable the university interest form only after the durable endpoint is available.

## Repository note

No backend implementation or deployment configuration was changed. Pre-existing local design notes, generated Next environment state, unused mascot source assets, and unrelated `output/` files remain outside this remediation scope.
