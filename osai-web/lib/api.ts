import type {
  ApproveResult,
  AskRequest,
  AskResponse,
  ConfirmActionResult,
  DataRouting,
  DismissActionResult,
  EvalRun,
  Integration,
  SearchRequest,
  SearchResponse,
  SyncRun,
  WorkflowRun,
} from "./types";
import { DataRoutingValidationError, parseDataRouting } from "./data-routing";

// The API origin (Render in prod, localhost in dev). Used only for full-URL
// browser navigations that must hit the API domain directly - the Google OAuth
// handshake, whose state cookie must be first-party to the API domain.
const API_ORIGIN = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// XHR/data calls go through the same-origin /api proxy (Vercel rewrite in prod,
// next.config rewrite in dev) so the httpOnly session cookie is first-party and
// SameSite=Lax protects writes. SSR (no window) calls the API origin directly.
const API_BASE_URL = typeof window === "undefined" ? API_ORIGIN : "/api";

// ─── Generic helpers ─────────────────────────────────────────────────────────

function getHeaders(extraHeaders: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extraHeaders };
  if (typeof window !== "undefined") {
    // Auth travels in the httpOnly session cookie (sent automatically with
    // credentials:"include"); X-Org-Id is only honoured server-side for the
    // public demo workspace.
    const orgId = localStorage.getItem("osai_org_id");
    if (orgId) headers["X-Org-Id"] = orgId;
  }
  return headers;
}

// The public demo and a real signed-in workspace can exist in the same browser.
// Never attach a stale real-session cookie to demo traffic: the backend gives an
// authenticated cookie precedence over X-Org-Id, which would otherwise let the
// demo UI read or write the customer's real org. Auth endpoints that explicitly
// create or clear the cookie opt back into "include" below.
function getRequestCredentials(): RequestCredentials {
  if (
    typeof window !== "undefined" &&
    localStorage.getItem("osai_org_id") === "demo-org"
  ) {
    return "omit";
  }
  return "include";
}

// Network requests are bounded by a timeout so a slow/unreachable backend can
// never leave the UI hanging on a spinner - on timeout or error we resolve to
// the provided fallback (typically demo data or null).
const DEFAULT_TIMEOUT_MS = 8000;

// Page-defining loads (integrations, dashboard metrics) get a longer budget:
// a Render cold start or a sync running in the same process can push the
// backend past 8s, and aborting there paints a false "check your connection"
// error over a healthy backend.
const SLOW_LOAD_TIMEOUT_MS = 20000;

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// A 401 means the session cookie is missing/expired/revoked. Drop the local
// auth flag and send the user back to sign in.
//
// Exception: the demo workspace has no real session, so any admin-gated write
// 401s by design - that must surface as an inline "not available in demo"
// message, not eject the whole session (QA ISSUE-002).
function handleUnauthorized(status: number) {
  if (status === 401 && typeof window !== "undefined") {
    if (localStorage.getItem("osai_org_id") === "demo-org") return;
    const onPublic = ["/login", "/demo", "/auth/callback"].some((p) =>
      window.location.pathname.startsWith(p)
    );
    if (!onPublic) {
      localStorage.removeItem("osai_authed");
      window.location.href = "/login";
    }
  }
}

async function apiGet<T>(
  path: string,
  fallback: T,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
  throwOnError = false,
  notFoundIsFallback = false
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      credentials: getRequestCredentials(),
      headers: getHeaders(),
      signal: controller.signal,
    });
    if (!res.ok) {
      if (res.status === 404 && notFoundIsFallback) return fallback;
      handleUnauthorized(res.status);
      const detail = await res.text();
      // Swallowing to a fallback keeps list pages resilient, but a silent 500
      // is indistinguishable from an empty workspace. Surface it so a broken
      // backend is diagnosable in the console instead of looking like "no data".
      console.warn(`GET ${path} failed (${res.status}); using fallback.`);
      if (throwOnError) {
        throw new ApiError(
          res.status,
          detail,
          `GET ${path} failed (${res.status}): ${detail}`
        );
      }
      return fallback;
    }
    return (await res.json()) as T;
  } catch (err) {
    if (throwOnError) throw err;
    // Network error or timeout abort - same reasoning as above.
    console.warn(`GET ${path} errored (${(err as Error)?.name ?? "error"}); using fallback.`);
    return fallback;
  } finally {
    clearTimeout(timer);
  }
}

// POST/agent calls can legitimately take longer than a GET (LLM round-trips),
// but must still be bounded so a hung backend can never leave the UI spinning
// forever. On timeout the abort surfaces as a thrown error, which callers
// (e.g. Ask) turn into an honest error or demo fallback.
const POST_TIMEOUT_MS = 30000;
const THREAD_TURN_TIMEOUT_MS = 2500;

async function apiPost<TBody, TResult>(
  path: string,
  body: TBody,
  timeoutMs: number = POST_TIMEOUT_MS,
  credentials: RequestCredentials = getRequestCredentials()
): Promise<TResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: getHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
      cache: "no-store",
      credentials,
      signal: controller.signal,
    });
    if (!res.ok) {
      handleUnauthorized(res.status);
      const detail = await res.text();
      throw new ApiError(
        res.status,
        detail,
        `POST ${path} failed (${res.status}): ${detail}`
      );
    }
    return (await res.json()) as TResult;
  } finally {
    clearTimeout(timer);
  }
}

async function apiPatch<TBody, TResult>(
  path: string,
  body: TBody,
  timeoutMs: number = POST_TIMEOUT_MS
): Promise<TResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      method: "PATCH",
      headers: getHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
      cache: "no-store",
      credentials: getRequestCredentials(),
      signal: controller.signal,
    });
    if (!res.ok) {
      handleUnauthorized(res.status);
      const detail = await res.text();
      throw new ApiError(
        res.status,
        detail,
        `PATCH ${path} failed (${res.status}): ${detail}`
      );
    }
    return (await res.json()) as TResult;
  } finally {
    clearTimeout(timer);
  }
}

async function apiDelete<TResult>(
  path: string,
  timeoutMs: number = POST_TIMEOUT_MS
): Promise<TResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      method: "DELETE",
      headers: getHeaders(),
      cache: "no-store",
      credentials: getRequestCredentials(),
      signal: controller.signal,
    });
    if (!res.ok) {
      handleUnauthorized(res.status);
      const detail = await res.text();
      throw new Error(`DELETE ${path} failed (${res.status}): ${detail}`);
    }
    return (await res.json()) as TResult;
  } finally {
    clearTimeout(timer);
  }
}

// ─── Authentication & Onboarding ─────────────────────────────────────────────

export type LoginCredentials = {
  email: string;
};

export type LoginSession = {
  user_id: string;
  org_id: string;
  role: string;
  token: string;
};

export type OrgOnboardPayload = {
  name: string;
  admin_email: string;
  admin_display_name: string;
};

export type OrgOnboardResponse = {
  org_id: string;
  name: string;
  admin_email: string;
  admin_display_name: string;
};

export function login(credentials: LoginCredentials): Promise<LoginSession> {
  return apiPost<LoginCredentials, LoginSession>(
    "/auth/login",
    credentials,
    POST_TIMEOUT_MS,
    "include"
  );
}

// Whether "Continue with Google" is available on this backend.
// Uses a longer timeout than the default: the free-tier backend can cold-start
// for 30–60s, and an 8s timeout would wrongly report Google as disabled (hiding
// the sign-in button) on the first page load after the instance has spun down.
export function getAuthConfig(strict = false) {
  return apiGet<{ google_enabled: boolean; email_login_enabled: boolean }>(
    "/auth/config",
    { google_enabled: false, email_login_enabled: true },
    60000,
    // strict lets the caller tell "the backend says Google is off" apart from
    // "the backend did not answer". Swallowed to the fallback they look
    // identical, which reports a cold-starting API as sign-in being disabled.
    strict
  );
}

export type SessionInfo = {
  user_id: string;
  email: string;
  display_name: string;
  org_id: string;
  org_name: string | null;
  role: string;
  is_admin: boolean;
  data_tier: string;
  permissions: string[];
  department_id: string | null;
};

// Who the current session belongs to and what it may do. The session cookie is
// httpOnly, so this is the only way the browser can learn its own role: use it
// to offer the right surfaces (admin-only Data sources) rather than rendering a
// control that 403s. Never a security boundary - the server gates every route.
// Returns null when unauthenticated (401) or the backend can't be reached, so
// callers fail closed to the non-admin view.
export function getSession(strict = false): Promise<SessionInfo | null> {
  return apiGet<SessionInfo | null>("/auth/session", null, DEFAULT_TIMEOUT_MS, strict);
}

export type DeploymentCapabilities = {
  environment: string;
  scheduler: boolean;
  automation_cadences: string[];
  connectors: boolean;
  sql_sources: boolean;
  workflow_execution: boolean;
  semantic_embeddings: boolean;
  embedding_model: string;
  google_oauth: boolean;
  email_login: boolean;
  zoom_webhook: boolean;
};

const SAFE_CAPABILITY_FALLBACK: DeploymentCapabilities = {
  environment: "unknown",
  scheduler: false,
  automation_cadences: ["manual"],
  connectors: false,
  sql_sources: false,
  workflow_execution: false,
  semantic_embeddings: false,
  embedding_model: "unknown",
  google_oauth: false,
  email_login: false,
  zoom_webhook: false,
};

// Deployment truth for optional runtime features. Callers that control an
// action should request strict mode so an outage cannot look like a capability.
export function getCapabilities(strict = false): Promise<DeploymentCapabilities> {
  return apiGet<DeploymentCapabilities>(
    "/capabilities",
    SAFE_CAPABILITY_FALLBACK,
    DEFAULT_TIMEOUT_MS,
    strict
  );
}

// Clear local, non-sensitive session state (cached org/user + the "authed"
// flag). The session JWT lives in an httpOnly cookie the browser can't touch, so
// callers that need the cookie gone must go through logout()/logoutAllSessions().
export function clearSession() {
  if (typeof window === "undefined") return;
  for (const k of [
    "osai_authed",
    "osai_token", // legacy: remove any JWT left by a pre-cookie session
    "osai_org_id",
    "osai_org_name",
    "osai_user_id",
    "osai_user_email",
    "osai_user_name",
    "osai_demo",
  ]) {
    localStorage.removeItem(k);
  }
}

// Persist the identity fields the UI reads (org/user), plus a non-sensitive flag
// marking that a session cookie exists. The JWT itself is never stored in JS.
export function markSignedIn(fields: {
  orgId: string;
  orgName?: string;
  email?: string;
  name?: string;
}) {
  if (typeof window === "undefined") return;
  if (fields.orgId !== "demo-org") {
    // Signing into a real org ends any demo session: stale demo flags (or a
    // legacy token key) must not leak DEMO_* fixtures into a customer
    // workspace (SHE-5) or keep a pre-cookie JWT around (QA E-03).
    localStorage.removeItem("osai_demo");
    localStorage.removeItem("osai_token");
  }
  localStorage.setItem("osai_authed", "1");
  localStorage.setItem("osai_org_id", fields.orgId);
  if (fields.orgName) localStorage.setItem("osai_org_name", fields.orgName);
  if (fields.email) localStorage.setItem("osai_user_email", fields.email);
  if (fields.name) localStorage.setItem("osai_user_name", fields.name);
}

// Exchange a JWT (from the OAuth redirect fragment) for an httpOnly session
// cookie on this origin, so the token never has to live in localStorage.
export function setSessionCookie(token: string) {
  return apiPost<{ token: string }, { ok: boolean }>(
    "/auth/session",
    { token },
    POST_TIMEOUT_MS,
    "include"
  );
}

// Clear only the server-side session cookie. Demo entry uses this as a
// best-effort cleanup while preserving the local demo identity it just set.
export async function clearServerSessionCookie(): Promise<void> {
  await apiPost<Record<string, never>, { ok: boolean }>(
    "/auth/logout",
    {},
    DEFAULT_TIMEOUT_MS,
    "include"
  );
}

// Sign out of this device: clear the server cookie, then local state.
export async function logout(): Promise<void> {
  try {
    await clearServerSessionCookie();
  } finally {
    clearSession();
  }
}

// Permanently delete the signed-in user's account, then clear the local session.
export async function deleteAccount(): Promise<void> {
  await apiDelete<{ deleted: boolean }>("/auth/account");
  clearSession();
}

// Revoke every outstanding session for this user (sign out everywhere): bumps the
// server-side token generation so all previously issued tokens stop working, then
// clears this device's session.
export async function logoutAllSessions(): Promise<void> {
  await apiPost<Record<string, never>, { revoked: boolean }>("/auth/logout-all", {});
  clearSession();
}

// Full URL to kick off the Google OAuth flow. Must hit the API origin directly
// (not the /api proxy): the OAuth state cookie set here has to be first-party to
// the API domain, which is where Google redirects the callback.
export function googleSignInUrl(): string {
  return new URL(`${API_ORIGIN}/auth/google/start`).toString();
}

export function onboardOrg(payload: OrgOnboardPayload): Promise<OrgOnboardResponse> {
  return apiPost<OrgOnboardPayload, OrgOnboardResponse>("/orgs", payload);
}

// Delete all ingested content for the current org (keeps connections) - used to
// clear seed/demo data before showing a customer their own workspace.
export function resetWorkspaceContent(orgId: string) {
  return apiPost<Record<string, never>, { org_id: string; deleted: Record<string, number> }>(
    `/orgs/${orgId}/reset-content`,
    {}
  );
}

// ─── Team (members, departments, invites) ────────────────────────────────────

export type TeamMember = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  department_id: string | null;
  department: string | null;
  data_tier: string;
  status: string;
};

export type MemberRemovalAssetCounts = {
  automations: number;
  private_threads: number;
  shared_threads: number;
  workflow_runs: number;
};

export type MemberRemovalBlockerCounts = {
  owned_uploads: number;
  document_access_grants: number;
  private_memories: number;
  ask_exchanges: number;
  pending_connector_actions: number;
};

export type MemberRemovalImpact = {
  member_id: string;
  member_email: string;
  member_display_name: string;
  assets: MemberRemovalAssetCounts;
  blockers: MemberRemovalBlockerCounts;
  preserved: { saved_artifacts: number };
  total_assets: number;
  total_blockers: number;
  requires_transfer: boolean;
  blocked: boolean;
};

export type Department = { id: string; name: string; color: string; members: number };

export type TeamInvite = {
  id: string;
  email: string;
  role: string;
  department_id: string | null;
  data_tier: string;
  status: string;
  invite_link: string;
};

export function getTeamMembers(strict = false) {
  return apiGet<TeamMember[]>("/team/members", [], DEFAULT_TIMEOUT_MS, strict);
}

export function getMemberRemovalImpact(userId: string, strict = false) {
  return apiGet<MemberRemovalImpact | null>(
    `/team/members/${userId}/removal-impact`,
    null,
    DEFAULT_TIMEOUT_MS,
    strict
  );
}

export function getDepartments(strict = false) {
  return apiGet<Department[]>("/team/departments", [], DEFAULT_TIMEOUT_MS, strict);
}

export function createDepartment(name: string, color?: string) {
  return apiPost<{ name: string; color?: string }, Department>("/team/departments", {
    name,
    color,
  });
}

export function renameDepartment(id: string, name: string) {
  return apiPatch<{ name: string }, Pick<Department, "id" | "name" | "color">>(
    `/team/departments/${id}`,
    { name }
  );
}

export function removeDepartment(id: string) {
  return apiDelete<{ deleted: boolean }>(`/team/departments/${id}`);
}

export function getInvites(strict = false) {
  return apiGet<TeamInvite[]>("/team/invites", [], DEFAULT_TIMEOUT_MS, strict);
}

export function createInvite(
  email: string,
  role: string,
  departmentId?: string | null,
  dataTier: string = "normal"
) {
  return apiPost<
    { email: string; role: string; department_id?: string | null; data_tier: string },
    TeamInvite
  >("/team/invites", {
    email,
    role,
    department_id: departmentId ?? null,
    data_tier: dataTier,
  });
}

export function revokeInvite(id: string) {
  return apiDelete<{ revoked: boolean }>(`/team/invites/${id}`);
}

export function updateMember(
  userId: string,
  patch: { role?: string; department_id?: string | null; data_tier?: string }
) {
  return apiPatch<typeof patch, { id: string; role: string; department_id: string | null }>(
    `/team/members/${userId}`,
    patch
  );
}

export function removeTeamMember(userId: string, transferToUserId?: string) {
  if (!transferToUserId) {
    return apiDelete<{ deleted: boolean }>(`/team/members/${userId}`);
  }
  return apiDelete<{ deleted: boolean }>(
    `/team/members/${userId}?transfer_to_user_id=${encodeURIComponent(transferToUserId)}`
  );
}

// ─── Integrations ────────────────────────────────────────────────────────────

// Data-routing reads and writes validate the JSON response before exposing it
// to the UI. A transport success with an unknown shape is not a saved policy.
export async function getDataRouting(): Promise<DataRouting> {
  try {
    const payload = await apiGet<unknown>(
      "/settings/data-routing",
      null,
      DEFAULT_TIMEOUT_MS,
      true
    );
    return parseDataRouting(payload);
  } catch (error) {
    if (
      error instanceof DataRoutingValidationError ||
      (error instanceof ApiError &&
        error.status === 503 &&
        error.detail.includes("Stored data-routing settings are invalid."))
    ) {
      throw new DataRoutingValidationError("Stored data-routing policy is invalid");
    }
    throw error;
  }
}

export async function patchDataRouting(
  routing: DataRouting,
  expectedRouting: DataRouting | null
): Promise<DataRouting> {
  const validated = parseDataRouting(routing);
  const expected = expectedRouting === null ? null : parseDataRouting(expectedRouting);
  const payload = await apiPatch<
    { routing: DataRouting; expected_routing: DataRouting | null },
    unknown
  >(
    "/settings/data-routing",
    { routing: validated, expected_routing: expected }
  );
  return parseDataRouting(payload);
}

export function getIntegrations(strict = false) {
  return apiGet<Integration[]>("/integrations", [], SLOW_LOAD_TIMEOUT_MS, strict);
}

export function triggerSync(connectorKey: string) {
  return apiPost<Record<string, never>, Record<string, unknown>>(
    `/integrations/${connectorKey}/sync`,
    {}
  );
}

// Native connector key → Composio toolkit slug (Composio uses its own slugs).
export const COMPOSIO_TOOLKIT: Record<string, string> = {
  notion: "notion",
  google_drive: "googledrive",
  slack: "slack",
  gmail: "gmail",
};

// One app in the Composio catalog (browse/search from the Add-connector dialog).
export type ComposioToolkit = {
  slug: string;
  name: string;
  no_auth: boolean;
  tools_count?: number | null;
  logo?: string | null;
  categories?: string[];
};

export type ComposioToolkitPage = {
  items: ComposioToolkit[];
  next_cursor?: string | null;
};

// Browse the Composio connectors whose content Sheldon can ingest.
export function listComposioToolkits(search?: string, cursor?: string) {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (cursor) params.set("cursor", cursor);
  const qs = params.toString();
  return apiGet<ComposioToolkitPage>(
    `/integrations/composio/toolkits${qs ? `?${qs}` : ""}`,
    { items: [], next_cursor: null },
    DEFAULT_TIMEOUT_MS,
    true
  );
}

export type ComposioConnectResult = {
  redirect_url?: string;
  connected_account_id?: string;
  error?: string;
  // Human-readable detail when error is a known code (e.g. "needs_api_key").
  message?: string;
};

// Begin a real OAuth connection for a connector via Composio. Returns a
// redirect_url the browser must open so the user can authorize the app.
export function composioConnect(connectorKey: string) {
  const toolkit = COMPOSIO_TOOLKIT[connectorKey] ?? connectorKey;
  return apiPost<Record<string, never>, ComposioConnectResult>(
    `/integrations/composio/connect/${toolkit}`,
    {}
  );
}

// Revoke the org's Composio connection for a connector, so a later Connect
// starts a fresh OAuth handshake instead of silently reusing a stale account.
export function composioDisconnect(connectorKey: string) {
  const toolkit = COMPOSIO_TOOLKIT[connectorKey] ?? connectorKey;
  return apiPost<Record<string, never>, { deleted: number }>(
    `/integrations/composio/disconnect/${toolkit}`,
    {}
  );
}

export type ConnectorDocument = {
  id: string;
  title: string;
  url: string | null;
  data_tier: "normal" | "amber" | "red";
  updated_at: string;
};

// Indexed documents for a connector (powers the Synced files view). Uses a high
// limit so the file list and its count reflect the full active index rather than
// a truncated slice that would disagree with the card's total.
export function getConnectorDocuments(connectorKey: string, strict = false) {
  return apiGet<ConnectorDocument[]>(
    `/integrations/${connectorKey}/documents?limit=500`,
    [],
    DEFAULT_TIMEOUT_MS,
    strict
  );
}

export function getHealthcheck(connectorKey: string, strict = false) {
  return apiGet<{ healthy: boolean; message: string }>(
    `/integrations/${connectorKey}/healthcheck`,
    { healthy: false, message: "Unknown" },
    DEFAULT_TIMEOUT_MS,
    strict
  );
}

// ─── Sync Runs ───────────────────────────────────────────────────────────────

export function getSyncRuns(strict = false) {
  return apiGet<SyncRun[]>("/sync-runs", [], DEFAULT_TIMEOUT_MS, strict);
}

export type SyncRunAggregate = {
  total_runs: number;
  status_counts: Record<string, number>;
  documents_seen: number;
  documents_indexed: number;
};

export type SyncRunPage = {
  items: SyncRun[];
  next_cursor: string | null;
  summary: SyncRunAggregate & { by_connector: Record<string, SyncRunAggregate> };
  as_of: string;
};

export function getSyncRunPage(limit = 25, cursor?: string, strict = false) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  return apiGet<SyncRunPage>(
    `/sync-runs/page?${params}`,
    {
      items: [],
      next_cursor: null,
      summary: {
        total_runs: 0,
        status_counts: {},
        documents_seen: 0,
        documents_indexed: 0,
        by_connector: {},
      },
      as_of: "",
    },
    DEFAULT_TIMEOUT_MS,
    strict
  );
}

// ─── Workflows ───────────────────────────────────────────────────────────────

export function getWorkflowRuns(strict = false) {
  return apiGet<WorkflowRun[]>("/workflows", [], DEFAULT_TIMEOUT_MS, strict);
}

export function getWorkflowRun(id: string, strict = false) {
  return apiGet<WorkflowRun | null>(
    `/workflows/${id}`,
    null,
    DEFAULT_TIMEOUT_MS,
    strict,
    true
  );
}

export function postWorkflow(
  inputText: string,
  destination = "manual",
  orgId?: string
) {
  return apiPost<
    { org_id: string; input_text: string; destination: string },
    WorkflowRun
  >("/workflows", { org_id: currentOrgId(orgId), input_text: inputText, destination });
}

export function approveActionItem(runId: string, itemId: string) {
  return apiPost<Record<string, never>, ApproveResult>(
    `/workflows/${runId}/action-items/${itemId}/approve`,
    {}
  );
}

// ─── Ask Sheldon agent (Phase 1 - POST /ask) ───────────────────────────────────────

function currentOrgId(orgId?: string) {
  return (
    orgId ??
    (typeof window !== "undefined"
      ? localStorage.getItem("osai_org_id") ?? "demo-org"
      : "demo-org")
  );
}

export function searchOsai(
  query: string,
  opts: { orgId?: string; departmentId?: string | null } = {}
): Promise<SearchResponse> {
  return apiPost<SearchRequest, SearchResponse>("/search", {
    org_id: currentOrgId(opts.orgId),
    query,
    department_id: opts.departmentId ?? null,
  });
}

export function askOsai(
  question: string,
  opts: {
    conversationId?: string | null;
    history?: AskRequest["history"];
    orgId?: string;
    departmentId?: string | null;
    intent?: AskRequest["intent"];
    threadId?: string | null;
    requestId?: string | null;
  } = {}
): Promise<AskResponse> {
  const body: AskRequest = {
    org_id: currentOrgId(opts.orgId),
    question,
    intent: opts.intent ?? "ask",
    conversation_id: opts.conversationId ?? null,
    history: opts.history,
    department_id: opts.departmentId ?? null,
    thread_id: opts.threadId ?? null,
    request_id: opts.requestId ?? null,
  };
  return apiPost<AskRequest, AskResponse>("/ask", body);
}

export function confirmAgentAction(
  actionId: string,
  conversationId: string
): Promise<ConfirmActionResult> {
  return apiPost<{ conversation_id: string }, ConfirmActionResult>(
    `/ask/actions/${actionId}/confirm`,
    { conversation_id: conversationId }
  );
}

// ─── Dashboard / Analytics metrics ────────────────────────────────────────────

export type DashboardMetrics = {
  total_documents: number;
  documents_by_connector: Record<string, number>;
  documents_by_tier: Record<string, number>;
  connectors_connected: number;
  connector_statuses?: Array<{
    key: string;
    auth_state: string;
    last_sync: string | null;
    sync_error: string | null;
  }>;
  pending_decisions?: number;
  pending_actions?: number;
  recent_decisions?: Array<{
    id: string;
    title: string;
    status: "proposed" | "approved" | "rejected";
    owner: string | null;
    date: string;
  }>;
  sync_runs_total: number;
  sync_runs_succeeded: number;
  last_sync_at: string | null;
  members: number;
  departments: number;
  automations: number;
  // When these counts were true. The server stamps it on every response, so a
  // view kept from an earlier load can say how fresh it is instead of implying
  // it is live.
  as_of?: string;
};

export function getDashboardMetrics(strict = false) {
  return apiGet<DashboardMetrics>("/dashboard/metrics", {
    total_documents: 0,
    documents_by_connector: {},
    documents_by_tier: {},
    connectors_connected: 0,
    connector_statuses: [],
    pending_decisions: 0,
    pending_actions: 0,
    recent_decisions: [],
    sync_runs_total: 0,
    sync_runs_succeeded: 0,
    last_sync_at: null,
    members: 0,
    departments: 0,
    automations: 0,
  }, SLOW_LOAD_TIMEOUT_MS, strict);
}

// ─── Automations (NL scheduled tasks) ─────────────────────────────────────────

export type DeliveryTarget = { channel: "slack"; target: string };

export type DeliveryOutcome = {
  status: "delivered" | "failed" | "skipped";
  via?: string;
  target?: string;
  error?: string;
};

export type Automation = {
  id: string;
  name: string;
  prompt: string;
  cadence: "manual" | "hourly" | "daily" | "weekly";
  enabled: boolean;
  status: "draft" | "active" | "paused";
  last_run_at: string | null;
  last_result: string | null;
  deliver_to: DeliveryTarget | null;
  last_delivery: DeliveryOutcome | null;
  updated_at: string | null;
  has_trigger_token?: boolean;
};

export function getAutomations(strict = false) {
  return apiGet<Automation[]>("/automations", [], DEFAULT_TIMEOUT_MS, strict);
}

export function createAutomation(input: {
  name: string;
  prompt: string;
  cadence: string;
  deliver_to?: DeliveryTarget | null;
}) {
  return apiPost<typeof input, Automation>("/automations", input);
}

export function updateAutomation(
  id: string,
  patch: Partial<
    Pick<Automation, "name" | "prompt" | "cadence" | "enabled" | "status">
  > & {
    // {} clears the delivery target; omit to leave unchanged.
    deliver_to?: DeliveryTarget | Record<string, never>;
  }
) {
  return apiPatch<typeof patch, Automation>(`/automations/${id}`, patch);
}

export function deleteAutomation(id: string) {
  return apiDelete<{ deleted: boolean }>(`/automations/${id}`);
}

export function mintAutomationToken(id: string) {
  return apiPost<Record<string, never>, { token: string; trigger_url: string }>(
    `/automations/${id}/token`,
    {}
  );
}

export function revokeAutomationToken(id: string) {
  return apiDelete<{ revoked: boolean }>(`/automations/${id}/token`);
}

export function runAutomation(id: string) {
  return apiPost<Record<string, never>, { id: string; result: string }>(
    `/automations/${id}/run`,
    {}
  );
}

// ─── Decision log (/decisions) ───────────────────────────────────────────────

export type ApiDecision = {
  id: string;
  title: string;
  status: "proposed" | "approved" | "rejected";
  impact: "critical" | "high" | "medium" | "low";
  owner: string | null;
  source: string;
  identifiedBy: "source" | "osai";
  tags: string[];
  date: string;
  updated_at: string | null;
};

export function getDecisions(strict = false) {
  return apiGet<ApiDecision[]>("/decisions", [], undefined, strict);
}

export function createDecision(input: {
  title: string;
  status: string;
  impact: string;
  owner?: string | null;
  source?: string;
  identified_by?: string;
  tags?: string[];
}) {
  return apiPost<typeof input, ApiDecision>("/decisions", input);
}

export function updateDecision(
  id: string,
  patch: Partial<{
    title: string;
    status: string;
    impact: string;
    owner: string | null;
    source: string;
    tags: string[];
  }>
) {
  return apiPatch<typeof patch, ApiDecision>(`/decisions/${id}`, patch);
}

export function deleteDecision(id: string) {
  return apiDelete<{ deleted: boolean }>(`/decisions/${id}`);
}

// ─── Answer feedback (POST /feedback) ────────────────────────────────────────

export function submitFeedback(input: {
  conversation_id: string | null;
  query: string;
  answer: string;
  rating: "up" | "down";
  comment?: string | null;
  wrong_sources?: string[] | null;
  correction?: string | null;
  retrieval_trace?: Record<string, unknown> | null;
}) {
  return apiPost<typeof input, { id: string | null; recorded: boolean }>(
    "/feedback",
    input
  );
}

// ─── Access map (who can access which tools, and at what data tier) ───────────

export type AccessMap = {
  users: { id: string; label: string; role: string; department?: string | null }[];
  connectors: { key: string; label: string; connected: boolean }[];
  access: {
    user_id: string;
    connector_key: string;
    tier: "normal" | "amber" | "red";
    doc_count: number;
  }[];
};

export function getAccessMap(strict = false) {
  return apiGet<AccessMap>("/graph/access", {
    users: [],
    connectors: [],
    access: [],
  }, DEFAULT_TIMEOUT_MS, strict);
}

// ─── Evals (explicit admin POST /evals) ───────────────────────────────────────

export function runEvalSuite() {
  // A full fixture run performs several model calls. It is deliberately an
  // explicit mutation with a longer bound, never a page-load GET.
  return apiPost<Record<string, never>, EvalRun>("/evals", {}, 180000);
}

// ─── Knowledge base uploads (POST /documents/upload) ─────────────────────────

export type UploadResult = {
  documents_indexed: number;
  vectors_indexed: number;
  vector_error: string | null;
  skipped: { filename: string; reason: string }[];
  visibility: UploadVisibility;
  documents: { id: string; title: string; data_tier: string }[];
};

/** Who can see an uploaded file. Translated to permission grants server-side. */
export type UploadVisibility = "personal" | "department" | "company" | "people";

export async function uploadDocuments(
  files: File[],
  opts: {
    visibility?: UploadVisibility;
    departmentId?: string;
    sharedWith?: string[]; // member ids, for visibility "people"
  } = {}
): Promise<UploadResult> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  form.append("visibility", opts.visibility ?? "personal");
  if (opts.departmentId) form.append("department_id", opts.departmentId);
  if (opts.sharedWith?.length) form.append("shared_with", opts.sharedWith.join(","));
  // No Content-Type header: the browser sets the multipart boundary itself.
  const res = await fetch(`${API_BASE_URL}/documents/upload`, {
    method: "POST",
    headers: getHeaders(),
    body: form,
    cache: "no-store",
    credentials: getRequestCredentials(),
  });
  if (!res.ok) {
    handleUnauthorized(res.status);
    const detail = await res.text();
    throw new Error(`Upload failed (${res.status}): ${detail}`);
  }
  return (await res.json()) as UploadResult;
}

// ─── Document access + notifications ────────────────────────────────────────

export type DocumentAccess = {
  visibility: UploadVisibility;
  shared_with: string[];
  department_id: string | null;
  people?: { id: string; name: string; email: string }[];
  title?: string;
};

export function updateDocumentAccess(
  docId: string,
  update: { visibility: UploadVisibility; shared_with?: string[]; department_id?: string | null }
) {
  return apiPatch<typeof update, DocumentAccess & { qdrant_error: string | null }>(
    `/documents/${docId}/access`,
    update
  );
}

export type AppNotification = {
  id: string;
  type: string;
  payload: { document_id?: string; thread_id?: string; title?: string; shared_by?: string; mentioned_by?: string };
  read: boolean;
  created_at: string | null;
};

export type NotificationPage = {
  items: AppNotification[];
  next_cursor: string | null;
  total: number;
  unread_count: number;
};

export function getNotifications(unreadOnly = true, strict = false) {
  return apiGet<AppNotification[]>(`/notifications?unread_only=${unreadOnly}`, [], DEFAULT_TIMEOUT_MS, strict);
}

export function getNotificationPage(
  limit = 25,
  cursor?: string,
  unreadOnly = false,
  strict = false
) {
  const query = new URLSearchParams({ limit: String(limit), unread_only: String(unreadOnly) });
  if (cursor) query.set("cursor", cursor);
  return apiGet<NotificationPage>(
    `/notifications/page?${query}`,
    { items: [], next_cursor: null, total: 0, unread_count: 0 },
    DEFAULT_TIMEOUT_MS,
    strict
  );
}

export function dismissAgentAction(
  actionId: string,
  conversationId: string
): Promise<DismissActionResult> {
  return apiPost<{ conversation_id: string }, DismissActionResult>(
    `/ask/actions/${actionId}/dismiss`,
    { conversation_id: conversationId }
  );
}

export function markNotificationRead(id: string) {
  return apiPost<Record<string, never>, AppNotification>(`/notifications/${id}/read`, {});
}

export function markAllNotificationsRead() {
  return apiPost<Record<string, never>, { updated: number }>("/notifications/read-all", {});
}

// ─── Threads (persisted Ask conversations) ───────────────────────────────────

export type ThreadSummary = {
  id: string;
  title: string;
  shared: boolean;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string | null;
  updated_at: string | null;
  turns?: number;
};

export type ThreadTurnRow = {
  id: string;
  role: "user" | "assistant";
  content: string;
  author_name: string | null;
  payload: Record<string, unknown> | null;
  created_at: string | null;
};

export function createThread(title: string) {
  return apiPost<{ title: string }, ThreadSummary>(
    "/threads",
    { title },
    THREAD_TURN_TIMEOUT_MS
  );
}

export function listThreads(strict = false) {
  return apiGet<ThreadSummary[]>("/threads", [], DEFAULT_TIMEOUT_MS, strict);
}

export function getThread(id: string, strict = false) {
  return apiGet<(ThreadSummary & { turns: ThreadTurnRow[] }) | null>(`/threads/${id}`, null, DEFAULT_TIMEOUT_MS, strict);
}

export function appendThreadTurn(
  id: string,
  turn: { role: "user"; content: string }
) {
  return apiPost<typeof turn, { id: string; recorded: boolean; mentioned: number }>(
    `/threads/${id}/turns`,
    turn,
    THREAD_TURN_TIMEOUT_MS
  );
}

export function patchThread(id: string, patch: { shared?: boolean; title?: string }) {
  return apiPatch<typeof patch, ThreadSummary>(`/threads/${id}`, patch);
}

// ─── Saved artifacts ─────────────────────────────────────────────────────────

export type SavedArtifactRow = {
  id: string;
  thread_id: string | null;
  title: string;
  kind: string;
  data: Record<string, unknown>;
  created_by_name: string | null;
  created_at: string | null;
};

export type SavedArtifactPage = {
  items: SavedArtifactRow[];
  next_cursor: string | null;
  total: number;
};

export function saveArtifact(input: {
  title: string;
  kind: string;
  data: Record<string, unknown>;
  thread_id?: string | null;
}) {
  return apiPost<typeof input, SavedArtifactRow>("/artifacts", input);
}

export function listArtifacts(strict = false) {
  return apiGet<SavedArtifactRow[]>("/artifacts", [], DEFAULT_TIMEOUT_MS, strict);
}

export function getArtifactPage(
  options: { limit?: number; cursor?: string | null } = {},
  strict = false
) {
  const params = new URLSearchParams({ limit: String(options.limit ?? 25) });
  if (options.cursor) params.set("cursor", options.cursor);
  return apiGet<SavedArtifactPage>(
    `/artifacts/page?${params.toString()}`,
    { items: [], next_cursor: null, total: 0 },
    DEFAULT_TIMEOUT_MS,
    strict
  );
}

export function deleteArtifact(id: string) {
  return apiDelete<{ deleted: boolean }>(`/artifacts/${id}`);
}

// ─── SQL answers (read-only structured data) ─────────────────────────────────

export type SqlSourceRow = { id: string; name: string; dsn: string };
export type SqlPlan = { sql: string; explanation: string };
export type SqlResult = { sql: string; columns: string[]; rows: unknown[][]; row_count: number };

export function listSqlSources(strict = false) {
  return apiGet<SqlSourceRow[]>("/sql/sources", [], DEFAULT_TIMEOUT_MS, strict);
}

export function addSqlSource(input: { name: string; dsn: string }) {
  return apiPost<typeof input, SqlSourceRow>("/sql/sources", input);
}

export function deleteSqlSource(id: string) {
  return apiDelete<{ deleted: boolean }>(`/sql/sources/${id}`);
}

export function planSqlQuery(input: { source_id: string; question: string }) {
  return apiPost<typeof input, SqlPlan>("/sql/plan", input);
}

export function executeSqlQuery(input: { source_id: string; sql: string }) {
  return apiPost<typeof input, SqlResult>("/sql/execute", input);
}

// ─── Slack /ask slash command ────────────────────────────────────────────────

export function mintSlackAskToken() {
  return apiPost<Record<string, never>, { token: string; request_url_path: string }>(
    "/settings/slack-ask-token",
    {}
  );
}

export function revokeSlackAskToken() {
  return apiDelete<{ revoked: boolean }>("/settings/slack-ask-token");
}
