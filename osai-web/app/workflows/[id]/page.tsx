"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowRight, Calendar, Check, Loader2, User } from "lucide-react";
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
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: 200, gap: 10 }}>
        <Loader2 className="animate-spin" size={20} />
        <p className="meta">Loading workflow run…</p>
      </div>
    );
  }

  if (!run) {
    return (
      <div>
        <p className="error-text">Workflow run not found.</p>
        <Link href="/automations" className="text-caption" style={{ color: "var(--accent)" }}>← Back to Automations</Link>
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
      <p className="breadcrumb">
        <Link href="/automations" style={{ color: "var(--accent)" }}>Automations</Link>
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
          <p className="run-link">{run.id}</p>
        </div>
      </div>

      {/* Meta card */}
      <div className="card" style={{ marginBottom: 24, padding: "16px 20px" }}>
        <div className="detail-meta-grid">
          {[
            { label: "Kind", value: run.kind },
            { label: "Destination", value: run.destination },
            { label: "Model", value: run.model_route },
            { label: "Data Tier", value: tier, color: tierColor },
            { label: "Created", value: new Date(run.created_at).toLocaleString() },
            { label: "Action Items", value: items.length.toString() },
          ].map((f) => (
            <div key={f.label}>
              <p style={{ fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 4 }} className="stat-card-label">
                {f.label}
              </p>
              <p className="text-caption" style={{ color: f.color ?? "var(--text-primary)", fontWeight: 600, margin: 0 }}>{f.value}</p>
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
          const DestinationIcon = destMeta?.icon;
          return (
            <div className="card" key={item.id} style={{ padding: "18px 22px" }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 12 }}>
                {destMeta && (
                  <span className="connector-inline-icon" style={{ marginTop: 1 }} aria-hidden>
                    {DestinationIcon && <DestinationIcon size={16} strokeWidth={1.8} />}
                  </span>
                )}
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <strong className="text-body-sm" style={{ color: "var(--text-primary)" }}>{item.title}</strong>
                    <span className={statusClass(item.status)}>{item.status}</span>
                  </div>
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                    {item.owner && <span className="meta" style={{ display: "inline-flex", alignItems: "center", gap: 3 }}><User size={11} /> {item.owner}</span>}
                    {item.due_date && <span className="meta" style={{ display: "inline-flex", alignItems: "center", gap: 3 }}><Calendar size={11} /> {item.due_date}</span>}
                    <span className="meta" style={{ display: "inline-flex", alignItems: "center", gap: 3 }}><ArrowRight size={11} /> {destMeta?.label ?? item.destination}</span>
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
                  className="text-micro"
                  style={{ color: "var(--accent)", display: "block", marginTop: 8 }}
                >
                  View in {destMeta?.label ?? item.destination} ↗
                </a>
              )}

              {item.status === "needs_review" && (
                <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 10 }}>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => handleApprove(item)}
                    disabled={approving === item.id}
                  >
                    {approving === item.id ? "Approving…" : "Approve & Execute →"}
                  </button>
                  {msgs[item.id] && (
                    <span className="success-text inline-flex items-center gap-1.5">
                      <Check className="size-3.5" strokeWidth={2} />
                      {msgs[item.id]}
                    </span>
                  )}
                </div>
              )}
              {item.status !== "needs_review" && msgs[item.id] && (
                <p className="success-text inline-flex items-center gap-1.5" style={{ marginTop: 8 }}>
                  <Check className="size-3.5" strokeWidth={2} />
                  {msgs[item.id]}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
