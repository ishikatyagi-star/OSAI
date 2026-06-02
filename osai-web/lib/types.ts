export type Integration = {
  key: string;
  display_name: string;
  capabilities: string[];
  auth_state: string;
  last_sync: string | null;
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

export type WorkflowRun = {
  id: string;
  kind: string;
  status: string;
  created_at: string;
  model: string;
  actions_created: number;
};
