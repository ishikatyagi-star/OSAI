// ─── Domain types matching backend Pydantic schemas ─────────────────────────

export type Integration = {
  key: string;
  display_name: string;
  capabilities: string[];
  auth_state: string;
  scopes: string[];
  last_sync: string | null;
  sync_error: string | null;
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
