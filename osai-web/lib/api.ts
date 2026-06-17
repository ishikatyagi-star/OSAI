import type {
  ApproveResult,
  AskRequest,
  AskResponse,
  ConfirmActionResult,
  DataRouting,
  EvalRun,
  GraphEdge,
  GraphEntity,
  Integration,
  SearchResponse,
  SyncRun,
  WorkflowRun,
} from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// ─── Generic helpers ─────────────────────────────────────────────────────────

function getHeaders(extraHeaders: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extraHeaders };
  if (typeof window !== "undefined") {
    const orgId = localStorage.getItem("osai_org_id");
    if (orgId) {
      headers["X-Org-Id"] = orgId;
    }
  }
  return headers;
}

// Network requests are bounded by a timeout so a slow/unreachable backend can
// never leave the UI hanging on a spinner — on timeout or error we resolve to
// the provided fallback (typically demo data or null).
const DEFAULT_TIMEOUT_MS = 8000;

async function apiGet<T>(
  path: string,
  fallback: T,
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      headers: getHeaders(),
      signal: controller.signal,
    });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  } finally {
    clearTimeout(timer);
  }
}

async function apiPost<TBody, TResult>(
  path: string,
  body: TBody
): Promise<TResult> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: getHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`POST ${path} failed (${res.status}): ${detail}`);
  }
  return (await res.json()) as TResult;
}

async function apiPatch<TBody, TResult>(
  path: string,
  body: TBody
): Promise<TResult> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "PATCH",
    headers: getHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`PATCH ${path} failed (${res.status}): ${detail}`);
  }
  return (await res.json()) as TResult;
}

async function apiPut<TBody, TResult>(
  path: string,
  body: TBody
): Promise<TResult> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "PUT",
    headers: getHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`PUT ${path} failed (${res.status}): ${detail}`);
  }
  return (await res.json()) as TResult;
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
  return apiPost<LoginCredentials, LoginSession>("/auth/login", credentials);
}

// Whether "Continue with Google" is available on this backend.
export function getAuthConfig() {
  return apiGet<{ google_enabled: boolean }>("/auth/config", {
    google_enabled: false,
  });
}

// Full URL to kick off the Google OAuth flow (browser navigates here).
export function googleSignInUrl(): string {
  return `${API_BASE_URL}/auth/google/start`;
}

export function onboardOrg(payload: OrgOnboardPayload): Promise<OrgOnboardResponse> {
  return apiPost<OrgOnboardPayload, OrgOnboardResponse>("/orgs", payload);
}

// Delete all ingested content for the current org (keeps connections) — used to
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
  status: string;
};

export type Department = { id: string; name: string; color: string; members: number };

export type TeamInvite = {
  id: string;
  email: string;
  role: string;
  department_id: string | null;
  status: string;
  invite_link: string;
};

export function getTeamMembers() {
  return apiGet<TeamMember[]>("/team/members", []);
}

export function getDepartments() {
  return apiGet<Department[]>("/team/departments", []);
}

export function createDepartment(name: string, color?: string) {
  return apiPost<{ name: string; color?: string }, Department>("/team/departments", {
    name,
    color,
  });
}

export function getInvites() {
  return apiGet<TeamInvite[]>("/team/invites", []);
}

export function createInvite(email: string, role: string, departmentId?: string | null) {
  return apiPost<
    { email: string; role: string; department_id?: string | null },
    TeamInvite
  >("/team/invites", { email, role, department_id: departmentId ?? null });
}

export function updateMember(
  userId: string,
  patch: { role?: string; department_id?: string | null }
) {
  return apiPatch<typeof patch, { id: string; role: string; department_id: string | null }>(
    `/team/members/${userId}`,
    patch
  );
}

// ─── Integrations ────────────────────────────────────────────────────────────

export function getIntegrations() {
  return apiGet<Integration[]>("/integrations", []);
}

export function triggerSync(connectorKey: string) {
  return apiPost<Record<string, never>, Record<string, unknown>>(
    `/integrations/${connectorKey}/sync`,
    {}
  );
}

// Native connector key → Composio toolkit slug (Composio uses its own slugs).
const COMPOSIO_TOOLKIT: Record<string, string> = {
  notion: "notion",
  google_drive: "googledrive",
  slack: "slack",
  freshdesk: "freshdesk",
};

export type ComposioConnectResult = {
  redirect_url?: string;
  connected_account_id?: string;
  error?: string;
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

export type ConnectorDocument = {
  id: string;
  title: string;
  url: string | null;
  data_tier: "normal" | "amber" | "red";
  updated_at: string;
};

// Recently indexed documents for a connector (powers the Synced files view).
export function getConnectorDocuments(connectorKey: string) {
  return apiGet<ConnectorDocument[]>(
    `/integrations/${connectorKey}/documents`,
    []
  );
}

export function getHealthcheck(connectorKey: string) {
  return apiGet<{ healthy: boolean; message: string }>(
    `/integrations/${connectorKey}/healthcheck`,
    { healthy: false, message: "Unknown" }
  );
}

// ─── Per-info data-tier rules ─────────────────────────────────────────────────

export type TierRule = { pattern: string; tier: "normal" | "amber" | "red" };

export function getTierRules(connectorKey: string) {
  return apiGet<{ connector_key: string; rules: TierRule[] }>(
    `/integrations/${connectorKey}/tier-rules`,
    { connector_key: connectorKey, rules: [] }
  );
}

export function putTierRules(connectorKey: string, rules: TierRule[]) {
  return apiPut<{ rules: TierRule[] }, { connector_key: string; rules: TierRule[] }>(
    `/integrations/${connectorKey}/tier-rules`,
    { rules }
  );
}

// ─── Sync Runs ───────────────────────────────────────────────────────────────

export function getSyncRuns() {
  return apiGet<SyncRun[]>("/sync-runs", []);
}

// ─── Search ──────────────────────────────────────────────────────────────────

export function postSearch(query: string, orgId?: string) {
  const currentOrgId = orgId ?? (typeof window !== "undefined" ? localStorage.getItem("osai_org_id") ?? "demo-org" : "demo-org");
  return apiPost<{ query: string; org_id: string }, SearchResponse>(
    "/search",
    { query, org_id: currentOrgId }
  );
}

// ─── Workflows ───────────────────────────────────────────────────────────────

export function getWorkflowRuns() {
  return apiGet<WorkflowRun[]>("/workflows", []);
}

export function getWorkflowRun(id: string) {
  return apiGet<WorkflowRun | null>(`/workflows/${id}`, null);
}

export function postWorkflow(
  inputText: string,
  destination = "manual",
  orgId?: string
) {
  const currentOrgId = orgId ?? (typeof window !== "undefined" ? localStorage.getItem("osai_org_id") ?? "demo-org" : "demo-org");
  return apiPost<
    { org_id: string; input_text: string; destination: string },
    WorkflowRun
  >("/workflows", { org_id: currentOrgId, input_text: inputText, destination });
}

export function approveActionItem(runId: string, itemId: string) {
  return apiPost<Record<string, never>, ApproveResult>(
    `/workflows/${runId}/action-items/${itemId}/approve`,
    {}
  );
}

// ─── Settings ────────────────────────────────────────────────────────────────

export function getDataRouting() {
  return apiGet<DataRouting | null>("/settings/data-routing", null);
}

export function patchDataRouting(routing: DataRouting) {
  return apiPatch<{ routing: DataRouting }, DataRouting>(
    "/settings/data-routing",
    { routing }
  );
}

// ─── Ask OSAI agent (Phase 1 — POST /ask) ────────────────────────────────────

function currentOrgId(orgId?: string) {
  return (
    orgId ??
    (typeof window !== "undefined"
      ? localStorage.getItem("osai_org_id") ?? "demo-org"
      : "demo-org")
  );
}

export function askOsai(
  question: string,
  opts: { conversationId?: string | null; history?: AskRequest["history"]; orgId?: string } = {}
): Promise<AskResponse> {
  const body: AskRequest = {
    org_id: currentOrgId(opts.orgId),
    question,
    conversation_id: opts.conversationId ?? null,
    history: opts.history,
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

// ─── Org knowledge graph (Phase 4 — GET /graph/*) ────────────────────────────

export function getGraphEntities(params: { type?: string; q?: string } = {}) {
  const qs = new URLSearchParams();
  if (params.type) qs.set("type", params.type);
  if (params.q) qs.set("q", params.q);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiGet<GraphEntity[]>(`/graph/entities${suffix}`, []);
}

export function getGraphEdges(params: { entityId?: string } = {}) {
  const suffix = params.entityId
    ? `?entity_id=${encodeURIComponent(params.entityId)}`
    : "";
  return apiGet<GraphEdge[]>(`/graph/edges${suffix}`, []);
}

// ─── Access map (who can access which tools, and at what data tier) ───────────

export type AccessMap = {
  users: { id: string; label: string; role: string }[];
  connectors: { key: string; label: string; connected: boolean }[];
  access: {
    user_id: string;
    connector_key: string;
    tier: "normal" | "amber" | "red";
    doc_count: number;
  }[];
};

export function getAccessMap() {
  return apiGet<AccessMap>("/graph/access", {
    users: [],
    connectors: [],
    access: [],
  });
}

// ─── Evals (Phase 6 — GET /evals) ─────────────────────────────────────────────

export function getEvalRun() {
  return apiGet<EvalRun | null>("/evals", null);
}
