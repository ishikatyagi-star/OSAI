"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { AlertTriangle, ArrowRight, Calendar, Check, Info, Loader2, User } from "lucide-react";
import { approveActionItem, getWorkflowRun } from "@/lib/api";
import { DEMO_WORKFLOW_RUNS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { ActionItem, WorkflowRun } from "@/lib/types";
import { brandText } from "@/lib/utils";
import { SheldonMascot } from "@/components/sheldon-mascot";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const TIER_COLORS: Record<string, string> = {
  normal: "var(--text-muted)",
  amber: "var(--yellow)",
  red: "var(--red)",
};

function statusClass(status: string) {
  if (status === "needs_review") return "badge badge-yellow";
  // In flight: claimed and pushing to the connector. Not green yet, because
  // nothing has landed in the customer's tool.
  if (status === "executing") return "badge badge-yellow";
  // "executed" is the pre-state-machine name for "completed"; older rows keep it.
  if (["approved", "executed", "completed", "succeeded"].includes(status)) return "badge badge-green";
  if (status === "failed") return "badge badge-red";
  // cancelled/skipped: deliberately not run, which is an outcome, not a fault.
  return "badge badge-grey";
}

export default function WorkflowDetailPage() {
  const params = useParams();
  const runId = params?.id as string;

  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Record<string, string>>({});
  const [pendingApprove, setPendingApprove] = useState<ActionItem | null>(null);
  const [approvalError, setApprovalError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    setLoadError("");
    if (isDemo()) {
      setRun(DEMO_WORKFLOW_RUNS.find((item) => item.id === runId) ?? null);
      setLoading(false);
      return;
    }
    getWorkflowRun(runId, true)
      .then(setRun)
      .catch(() => setLoadError("This workflow run could not be loaded. Check your connection and try again."))
      .finally(() => setLoading(false));
  }, [reloadKey, runId]);

  async function handleApprove(item: ActionItem) {
    setApproving(item.id);
    setApprovalError("");
    try {
      let outcomeStatus = "approved";
      let outcomeMessage = "Approved in the demo; no external tool was changed.";
      if (isDemo()) {
        setRun((prev) =>
          prev
            ? {
                ...prev,
                action_items: (prev.action_items ?? []).map((action) =>
                  action.id === item.id ? { ...action, status: "approved" } : action
                ),
              }
            : prev
        );
      } else {
        const result = await approveActionItem(runId, item.id);
        outcomeStatus = result.status;
        outcomeMessage = brandText(result.message);
        setRun((prev) =>
          prev
            ? {
                ...prev,
                action_items: (prev.action_items ?? []).map((action) =>
                  action.id === item.id
                    ? { ...action, status: result.status, external_url: result.external_url }
                    : action
                ),
              }
            : prev
        );
      }
      setMsgs((prev) => ({ ...prev, [item.id]: outcomeMessage }));
      if (outcomeStatus === "failed") {
        setApprovalError(outcomeMessage || "The destination rejected the action. Review the connection and retry.");
        return;
      }
      setPendingApprove(null);
    } catch {
      setApprovalError("The action was not approved or executed. Check the destination and try again.");
    } finally {
      setApproving(null);
    }
  }

  if (loading) {
    return (
      <div className="card async-state" role="status" aria-live="polite">
        <Loader2 className="animate-spin" size={20} aria-hidden="true" />
        <p className="meta">Loading workflow run…</p>
      </div>
    );
  }

  if (!run) {
    if (loadError) {
      return (
        <div className="card mascot-error-state" role="alert">
          <SheldonMascot state="recovering" size={104} />
          <p className="error-text">{loadError}</p>
          <button type="button" className="btn btn-primary" onClick={() => setReloadKey((key) => key + 1)}>Retry</button>
        </div>
      );
    }
    return (
      <div className="card mascot-error-state">
        <SheldonMascot state="recovering" size={104} />
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

      {approvalError && (
        <div className="card" role="alert" style={{ marginBottom: 16, padding: "10px 14px", color: "var(--red)" }}>
          {approvalError}
        </div>
      )}

      {items.length === 0 && (
        <p className="empty-state">No action items extracted from this run.</p>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {items.map((item) => {
          const destMeta = CONNECTOR_META[item.destination];
          const DestinationIcon = destMeta?.icon;
          return (
            <div className="card workflow-action-card" key={item.id}>
              <div className="workflow-action-header">
                {destMeta && (
                  <span className="connector-inline-icon" style={{ marginTop: 1 }} aria-hidden>
                    {DestinationIcon && <DestinationIcon size={16} strokeWidth={1.8} />}
                  </span>
                )}
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <strong className="text-body-sm" style={{ color: "var(--text-primary)" }}>{brandText(item.title)}</strong>
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
                <blockquote className="source-quote">&ldquo;{brandText(item.source_quote)}&rdquo;</blockquote>
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

              {["needs_review", "failed"].includes(item.status) && (
                <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 10 }}>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => { setApprovalError(""); setPendingApprove(item); }}
                    disabled={approving === item.id}
                    aria-label={`Approve and execute: ${brandText(item.title)}`}
                  >
                    {approving === item.id ? "Approving…" : item.status === "failed" ? "Retry execution →" : "Approve & Execute →"}
                  </button>
                </div>
              )}
              {msgs[item.id] && (
                <p
                  className="inline-flex items-center gap-1.5"
                  role={item.status === "failed" ? "alert" : "status"}
                  style={{
                    marginTop: 8,
                    color: item.status === "failed" ? "var(--red)" : item.status === "skipped" ? "var(--blue)" : "var(--green)",
                  }}
                >
                  {item.status === "failed" ? (
                    <AlertTriangle className="size-3.5" strokeWidth={2} />
                  ) : item.status === "skipped" ? (
                    <Info className="size-3.5" strokeWidth={2} />
                  ) : (
                    <Check className="size-3.5" strokeWidth={2} />
                  )}
                  {msgs[item.id]}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {pendingApprove && (
        <Dialog open onOpenChange={(open) => !open && !approving && setPendingApprove(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Approve and execute this action?</DialogTitle>
              <DialogDescription>
                “{brandText(pendingApprove.title)}” will be sent to {brandText(CONNECTOR_META[pendingApprove.destination]?.label ?? pendingApprove.destination)}. This may change an external tool.
              </DialogDescription>
            </DialogHeader>
            {approvalError && <p className="error-text" role="alert">{approvalError}</p>}
            <DialogFooter>
              <button type="button" className="btn" onClick={() => setPendingApprove(null)} disabled={!!approving}>Cancel</button>
              <button type="button" className="btn btn-primary" onClick={() => handleApprove(pendingApprove)} disabled={!!approving}>
                {approving ? "Approving…" : "Approve action"}
              </button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
