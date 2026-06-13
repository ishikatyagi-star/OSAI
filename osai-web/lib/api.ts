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

export function onboardOrg(payload: OrgOnboardPayload): Promise<OrgOnboardResponse> {
  return apiPost<OrgOnboardPayload, OrgOnboardResponse>("/orgs", payload);
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

export function getHealthcheck(connectorKey: string) {
  return apiGet<{ healthy: boolean; message: string }>(
    `/integrations/${connectorKey}/healthcheck`,
    { healthy: false, message: "Unknown" }
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

// ─── Evals (Phase 6 — GET /evals) ─────────────────────────────────────────────

export function getEvalRun() {
  return apiGet<EvalRun | null>("/evals", null);
}
