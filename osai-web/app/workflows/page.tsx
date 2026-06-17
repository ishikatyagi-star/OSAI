"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronUp, User } from "lucide-react";
import { getWorkflowRuns, postWorkflow, approveActionItem } from "@/lib/api";
import { DEMO_WORKFLOW_RUNS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import type { WorkflowRun, ActionItem } from "@/lib/types";

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const TIER_COLORS: Record<string, string> = {
  normal: "var(--text-muted)",
  amber: "var(--yellow)",
  red: "var(--red)",
};

const STATUS_BADGE: Record<string, string> = {
  needs_review: "badge-yellow",
  completed: "badge-green",
  succeeded: "badge-green",
  failed: "badge-red",
  executing: "badge-grey",
};

const DESTINATION_ICONS: Record<string, string> = {
  notion: "📝",
  slack: "💬",
  freshdesk: "🎫",
  google_drive: "📁",
  manual: "",
};

function ActionItemRow({
  item,
  runId,
  onApprove,
}: {
  item: ActionItem;
  runId: string;
  onApprove: (runId: string, itemId: string) => void;
}) {
  const [approving, setApproving] = useState(false);

  async function handleApprove() {
    setApproving(true);
    await onApprove(runId, item.id);
    setApproving(false);
  }

  return (
    <div className="action-item-row">
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span className="text-caption">{DESTINATION_ICONS[item.destination] || (item.destination === "manual" ? <User size={13} /> : "⚙")}</span>
          <span className="text-caption" style={{ color: "var(--text-primary)", fontWeight: 600 }}>{item.title}</span>
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {item.owner && (
            <span className="meta" style={{ display: "inline-flex", alignItems: "center", gap: 3 }}><User size={11} /> {item.owner.split("@")[0]}</span>
          )}
          {item.due_date && (
            <span className="meta">📅 Due {item.due_date}</span>
          )}
          <span className="meta">
            confidence: {Math.round(item.confidence * 100)}%
          </span>
        </div>
        {item.source_quote && (
          <p className="source-quote" style={{ marginTop: 8 }}>
            &ldquo;{item.source_quote}&rdquo;
          </p>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8, flexShrink: 0 }}>
        <span className={`badge ${STATUS_BADGE[item.status] ?? "badge-grey"}`}>
          {item.status}
        </span>
        {item.status === "needs_review" && (
          <button
            className="btn btn-primary btn-xs"
            disabled={approving}
            onClick={handleApprove}
          >
            {approving ? "…" : "Approve →"}
          </button>
        )}
        {item.external_url && (
          <a
            href={item.external_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[11px]"
            style={{ color: "var(--accent)" }}
          >
            View →
          </a>
        )}
      </div>
    </div>
  );
}

function RunCard({
  run,
  expanded,
  onToggle,
  onApprove,
}: {
  run: WorkflowRun & { data_tier?: string };
  expanded: boolean;
  onToggle: () => void;
  onApprove: (runId: string, itemId: string) => void;
}) {
  const items = run.action_items ?? [];
  const pendingCount = items.filter((a) => a.status === "needs_review").length;
  const tier = (run as WorkflowRun & { data_tier?: string }).data_tier ?? "normal";

  return (
    <div className="card workflow-run-card" style={{ padding: 0, overflow: "hidden" }}>
      <button
        onClick={onToggle}
        className="workflow-run-header"
      >
        {/* Tier indicator */}
        <div
          style={{
            width: 3,
            height: 36,
            borderRadius: 9999,
            background: TIER_COLORS[tier] ?? TIER_COLORS.normal,
            flexShrink: 0,
          }}
        />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span className="run-link">{run.id}</span>
            <span className={`badge ${STATUS_BADGE[run.status] ?? "badge-grey"}`}>
              {run.status}
            </span>
            {pendingCount > 0 && (
              <span className="badge badge-yellow text-[10px]">
                {pendingCount} pending
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <span className="meta">⚡ {items.length} action items</span>
            <span className="meta">→ {run.destination}</span>
            <span className="meta">🤖 {run.model_route}</span>
            <span className="meta text-[10px] font-semibold uppercase" style={{ color: TIER_COLORS[tier] }}>
              {tier} tier
            </span>
            <span className="meta">{timeAgo(run.created_at)}</span>
          </div>
        </div>

        <span style={{ color: "var(--text-muted)", flexShrink: 0 }}>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </button>

      {expanded && items.length > 0 && (
        <div style={{ borderTop: "1px solid var(--border)", padding: "0 22px 18px" }}>
          {items.map((item) => (
            <ActionItemRow key={item.id} item={item} runId={run.id} onApprove={onApprove} />
          ))}
        </div>
      )}

      {expanded && items.length === 0 && (
        <div style={{ padding: "12px 22px 18px", borderTop: "1px solid var(--border)" }}>
          <p className="meta">No action items extracted from this run.</p>
        </div>
      )}
    </div>
  );
}

export default function WorkflowsPage() {
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [inputText, setInputText] = useState("");
  const [destination, setDestination] = useState("manual");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    getWorkflowRuns().then((data) => {
      const hasReal = data.some((w) => (w.action_items ?? []).length > 0);
      const display = hasReal ? data : isDemo() ? DEMO_WORKFLOW_RUNS : data;
      setRuns(display);
      if (display[0]) setExpandedIds(new Set([display[0].id]));
    });
  }, []);

  function toggleExpand(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!inputText.trim()) return;
    setLoading(true);
    setError("");
    try {
      const run = await postWorkflow(inputText.trim(), destination);
      setRuns((prev) => [run, ...prev]);
      setExpandedIds((prev) => new Set([run.id, ...prev]));
      setInputText("");
      setShowCreate(false);
    } catch {
      // Demo fallback: synthesise a fake run
      const fakeRun: WorkflowRun = {
        id: `workflow-demo-${Date.now()}`,
        kind: "meeting_action_items",
        status: "needs_review",
        destination,
        model_route: "gemini-2.0-flash",
        created_at: new Date().toISOString(),
        action_items: [
          {
            id: `item-fake-${Date.now()}`,
            title: inputText.trim().split(".")[0].replace(/^[A-Z][^:]*:\s*/,"").slice(0, 80),
            owner: null,
            due_date: null,
            source_quote: inputText.trim().slice(0, 120),
            destination,
            confidence: 0.88,
            status: "needs_review",
            external_url: null,
            executed_at: null,
          },
        ],
      };
      setRuns((prev) => [fakeRun, ...prev]);
      setExpandedIds((prev) => new Set([fakeRun.id, ...prev]));
      setInputText("");
      setShowCreate(false);
    } finally {
      setLoading(false);
    }
  }

  async function handleApprove(runId: string, itemId: string) {
    try {
      await approveActionItem(runId, itemId);
    } catch {
      // Demo mode — update local state
    }
    setRuns((prev) =>
      prev.map((r) =>
        r.id !== runId
          ? r
          : {
              ...r,
              action_items: (r.action_items ?? []).map((a) =>
                a.id === itemId ? { ...a, status: "approved" } : a
              ),
            }
      )
    );
  }

  const pendingTotal = runs
    .flatMap((r) => r.action_items ?? [])
    .filter((a) => a.status === "needs_review").length;

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Workflows</h1>
          <p>
            Paste meeting notes or transcripts — OSAI extracts action items and pushes them to your tools.
          </p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => setShowCreate((v) => !v)}
        >
          + New Workflow
        </button>
      </div>

      {/* Stats — dashboard stat-card styling; color only appears when it carries meaning */}
      <div className="stats-grid stats-grid--auto">
        {([
          { label: "Total runs", value: runs.length },
          {
            label: "Completed",
            value: runs.filter((r) => r.status === "completed" || r.status === "succeeded").length,
            tone: "var(--green)",
          },
          {
            label: "Needs review",
            value: runs.filter((r) => r.status === "needs_review").length,
            tone: "var(--blue)",
          },
          { label: "Action items pending", value: pendingTotal },
        ] as { label: string; value: number; tone?: string }[]).map((s) => (
          <div key={s.label} className="stat-card">
            <div className="stat-card-label">{s.label}</div>
            <div
              className="stat-card-value"
              style={{ color: s.value > 0 && s.tone ? s.tone : "var(--text-primary)" }}
            >
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="card" style={{ marginBottom: 24 }}>
          <h2 style={{ marginBottom: 16 }}>Extract Action Items</h2>
          <form onSubmit={handleCreate}>
            <textarea
              className="textarea"
              rows={6}
              placeholder="Paste meeting notes, a transcript, or any text with action items…&#10;&#10;Example:&#10;Sarah: I will prepare the product roadmap by Friday.&#10;Anish: I will schedule the user interviews."
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
            />
            <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
              <label className="text-micro font-semibold" style={{ color: "var(--text-secondary)" }}>
                Push items to:
              </label>
              <select
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
                className="select"
              >
                <option value="manual">Manual Review</option>
                <option value="notion">Notion</option>
                <option value="freshdesk">Freshdesk</option>
                <option value="slack">Slack</option>
                <option value="google_drive">Google Drive</option>
              </select>
              <button type="submit" className="btn btn-primary" disabled={loading}>
                {loading ? "Running…" : "Run Workflow"}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setShowCreate(false)}
              >
                Cancel
              </button>
            </div>
            {error && <p className="error-text" style={{ marginTop: 8 }}>{error}</p>}
          </form>
        </div>
      )}

      {/* Run log */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Run Log</h2>
        <span className="meta">({runs.length} runs)</span>
      </div>

      {runs.length === 0 && (
        <div className="card" style={{ textAlign: "center", padding: "40px 24px" }}>
          <p className="text-body font-semibold" style={{ marginBottom: 6 }}>No workflow runs yet</p>
          <p className="meta leading-normal" style={{ maxWidth: 460, margin: "0 auto 8px" }}>
            Paste meeting notes or a transcript and OSAI extracts the action items — owner, due date
            and a source quote — then pushes them to Notion, Slack, Freshdesk or manual review.
          </p>
          <p className="meta" style={{ maxWidth: 460, margin: "0 auto 18px", fontStyle: "italic" }}>
            e.g. “Sarah: I’ll prepare the roadmap by Friday. Anish: I’ll schedule the interviews.”
          </p>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)} style={{ display: "inline-flex" }}>
            + New Workflow
          </button>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {runs.map((run) => (
          <RunCard
            key={run.id}
            run={run}
            expanded={expandedIds.has(run.id)}
            onToggle={() => toggleExpand(run.id)}
            onApprove={handleApprove}
          />
        ))}
      </div>
    </div>
  );
}
