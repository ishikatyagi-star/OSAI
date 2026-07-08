// ─── Domain types matching backend Pydantic schemas ─────────────────────────

export type Integration = {
  key: string;
  display_name: string;
  capabilities: string[];
  auth_state: string;
  scopes: string[];
  last_sync: string | null;
  sync_error: string | null;
  // Which external account is currently connected (e.g. the Google user), and
  // the previous one + when it changed, so the UI can show reconnect state.
  account_email?: string | null;
  previous_account_email?: string | null;
  last_reconnected_at?: string | null;
};

export type SyncRun = {
  id: string;
  connector_key: string;
  status: string;
  started_at: string;
  documents_seen: number;
  documents_indexed: number;
  error: string | null;
};

export type ActionItem = {
  id: string;
  title: string;
  owner: string | null;
  due_date: string | null;
  source_quote: string | null;
  destination: string;
  confidence: number;
  status: string;
  external_url: string | null;
  executed_at: string | null;
};

export type WorkflowRun = {
  id: string;
  kind: string;
  status: string;
  destination: string;
  model_route: string;
  created_at: string;
  action_items?: ActionItem[];
};

export type SourceCitation = {
  source_tool: string;
  source_record_title: string;
  url: string | null;
  confidence: number;
};

export type SearchResponse = {
  answer: string;
  citations: SourceCitation[];
  enough_context: boolean;
};

export type DataRouting = {
  normal: { allowed_connectors: string[]; llm_allowed: boolean };
  amber: { allowed_connectors: string[]; llm_allowed: boolean };
  red: { allowed_connectors: string[]; llm_allowed: boolean };
};

export type ApproveResult = {
  item_id: string;
  status: string;
  destination: string;
  external_url: string | null;
  message: string;
};


// ─── Ask OSAI agent (Phase 1 — POST /ask) ───────────────────────────────────

export type ChatRole = "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type AgentActionStatus = "proposed" | "executed" | "failed" | "skipped";

export type AgentAction = {
  id: string;
  tool: string;
  action: string;
  summary: string;
  status: AgentActionStatus;
  requires_confirmation: boolean;
  params?: Record<string, unknown>;
  external_url: string | null;
  error: string | null;
};

export type AskRequest = {
  org_id: string;
  question: string;
  conversation_id?: string | null;
  history?: ChatMessage[];
};

export type AskResponse = {
  conversation_id: string;
  answer: string;
  citations: SourceCitation[];
  actions_taken: AgentAction[];
  enough_context: boolean;
  model_route?: string;
  latency_ms?: number;
  // Which engine answered: in-house RAG ("osai") or the Hermes sidecar ("hermes").
  via?: "osai" | "hermes";
};

export type ConfirmActionResult = {
  id: string;
  status: "executed" | "failed";
  external_url: string | null;
  message: string;
  error: string | null;
};

// ─── Org knowledge graph (Phase 4 — GET /graph/*) ────────────────────────────

export type GraphEntityType =
  | "person"
  | "project"
  | "decision"
  | "source"
  | "department"
  | "ticket";

export type GraphEntity = {
  id: string;
  type: GraphEntityType;
  label: string;
  summary: string | null;
  source_tool: string | null;
  attributes: Record<string, string>;
  degree: number;
};

export type GraphEdgeType =
  | "owns"
  | "attended"
  | "works_at"
  | "references"
  | "blocks"
  | "decided";

export type GraphEdge = {
  id: string;
  source_id: string;
  target_id: string;
  type: GraphEdgeType;
  label: string;
  confidence: number;
  source_tool: string | null;
};

// ─── Evals (Phase 6 — GET /evals) ────────────────────────────────────────────

export type EvalCategory = "ticket_triage" | "ownership" | "routing" | "qa";

export type EvalCase = {
  id: string;
  category: EvalCategory;
  question: string;
  expected: string;
  actual: string;
  passed: boolean;
  score: number;
  latency_ms: number;
  notes: string | null;
};

export type EvalRun = {
  run_id: string;
  created_at: string;
  model_route: string;
  pass_rate: number;
  total: number;
  passed: number;
  failed: number;
  cases: EvalCase[];
};
