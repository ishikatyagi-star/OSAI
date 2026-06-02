import type { Integration, SyncRun, WorkflowRun } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function apiGet<T>(path: string, fallback: T): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
    if (!response.ok) {
      return fallback;
    }
    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}

export function getIntegrations() {
  return apiGet<Integration[]>("/integrations", []);
}

export function getSyncRuns() {
  return apiGet<SyncRun[]>("/sync-runs", []);
}

export function getWorkflowRuns() {
  return apiGet<WorkflowRun[]>("/workflows", []);
}
