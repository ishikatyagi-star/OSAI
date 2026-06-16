"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { approveActionItem, getWorkflowRun } from "@/lib/api";
import { DEMO_WORKFLOW_RUNS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { ActionItem, WorkflowRun } from "@/lib/types";

const TIER_COLORS: Record<string, string> = {
  normal: "var(--text-muted)",
  amber: "var(--yellow)",
  red: "var(--red)",
};

function statusClass(status: string) {
  if (status === "needs_review") return "badge badge-yellow";
  if (["approved", "executed", "completed", "succeeded"].includes(status)) return "badge badge-green";
  if (status === "failed") return "badge badge-red";
  return "badge badge-grey";
}

export default function WorkflowDetailPage() {
  const params = useParams();
  const runId = params?.id as string;

  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!runId) return;
    getWorkflowRun(runId).then((data) => {
      if (data) {
        setRun(data);
      } else if (isDemo()) {
        setRun(DEMO_WORKFLOW_RUNS.find((r) => r.id === runId) ?? null);
      } else {
        setRun(null);
      }
      setLoading(false);
    });
  }, [runId]);

  async function handleApprove(item: ActionItem) {
    setApproving(item.id);
    try {
      const result = await approveActionItem(runId, item.id);
      setMsgs((prev) => ({ ...prev, [item.id]: result.message }));
      const updated = await getWorkflowRun(runId);
      setRun(updated);
    } catch {
      // Demo mode — update locally
      setRun((prev) =>
        prev
          ? {
              ...prev,
              action_items: (prev.action_items ?? []).map((a) =>
                a.id === item.id ? { ...a, status: "approved" } : a
              ),
            }
          : prev
      );
      setMsgs((prev) => ({ ...prev, [item.id]: "Approved (demo mode)" }));
    } finally {
      setApproving(null);
    }
  }

  if (loading) {
    return (
      <div>
        <p className="meta">Loading workflow run…</p>
      </div>
    );
  }

  if (!run) {
    return (
      <div>
        <p className="error-text">Workflow run not found.</p>
        <Link href="/workflows" style={{ fontSize: 13, color: "var(--accent)" }}>← Back to workflows</Link>
      </div>
    );
  }

  const items: ActionItem[] = run.action_items ?? [];
  const tier = (run as WorkflowRun & { data_tier?: string }).data_tier ?? "normal";
  const tierColor = TIER_COLORS[tier] ?? TIER_COLORS.normal;
  const pendingCount = items.filter((a) => a.status === "needs_review").length;

  return (
    <div>
      {/* Breadcrumb */}
      <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 20 }}>
        <Link href="/workflows" style={{ color: "var(--accent)" }}>Workflows</Link>
        {" / "}
        <span className="run-link">{run.id}</span>
      </p>

      {/* Header */}
      <div className="page-header">
        <div className="page-header-left">
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <h1>Workflow Run</h1>
            <span className={statusClass(run.status)}>{run.status}</span>
            {pendingCount > 0 && (
              <span className="badge badge-yellow">{pendingCount} pending approval</span>
            )}
          </div>
          <p className="run-link" style={{ fontSize: 12 }}>{run.id}</p>
        </div>
      </div>

      {/* Meta card */}
      <div className="card" style={{ marginBottom: 24, padding: "16px 20px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 16 }}>
          {[
            { label: "Kind", value: run.kind },
            { label: "Destination", value: run.destination },
            { label: "Model", value: run.model_route },
            { label: "Data Tier", value: tier, color: tierColor },
            { label: "Created", value: new Date(run.created_at).toLocaleString() },
            { label: "Action Items", value: items.length.toString() },
          ].map((f) => (
            <div key={f.label}>
              <p style={{ fontSize: 10, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 4 }}>
                {f.label}
              </p>
              <p style={{ fontSize: 13, color: f.color ?? "var(--text-primary)", fontWeight: 600, margin: 0 }}>{f.value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Action items */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Action Items</h2>
        <span className="meta">({items.length})</span>
      </div>

      {items.length === 0 && (
        <p className="empty-state">No action items extracted from this run.</p>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {items.map((item) => {
          const destMeta = CONNECTOR_META[item.destination];
          return (
            <div className="card" key={item.id} style={{ padding: "18px 22px" }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 12 }}>
                {destMeta && (
                  <span style={{ fontSize: 20, marginTop: 1 }}>{destMeta.icon}</span>
                )}
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <strong style={{ fontSize: 14, color: "var(--text-primary)" }}>{item.title}</strong>
                    <span className={statusClass(item.status)}>{item.status}</span>
                  </div>
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                    {item.owner && <span className="meta">👤 {item.owner}</span>}
                    {item.due_date && <span className="meta">📅 {item.due_date}</span>}
                    <span className="meta">→ {destMeta?.label ?? item.destination}</span>
                    <span className="meta">confidence: {(item.confidence * 100).toFixed(0)}%</span>
                  </div>
                </div>
              </div>

              {item.source_quote && (
                <blockquote className="source-quote">&ldquo;{item.source_quote}&rdquo;</blockquote>
              )}

              {item.external_url && (
                <a
                  href={item.external_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ fontSize: 12, color: "var(--accent)", display: "block", marginTop: 8 }}
                >
                  View in {destMeta?.label ?? item.destination} ↗
                </a>
              )}

              {item.status === "needs_review" && (
                <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 10 }}>
                  <button
                    className="btn btn-primary"
                    style={{ padding: "8px 18px", fontSize: 12 }}
                    onClick={() => handleApprove(item)}
                    disabled={approving === item.id}
                  >
                    {approving === item.id ? "Approving…" : "Approve & Execute →"}
                  </button>
                  {msgs[item.id] && (
                    <span className="success-text" style={{ fontSize: 12 }}>✓ {msgs[item.id]}</span>
                  )}
                </div>
              )}
              {item.status !== "needs_review" && msgs[item.id] && (
                <p className="success-text" style={{ fontSize: 12, marginTop: 8 }}>✓ {msgs[item.id]}</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
