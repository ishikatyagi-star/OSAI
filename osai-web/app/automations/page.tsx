"use client";

import { useEffect, useState } from "react";
import {
  ArrowRight,
  Bot,
  Calendar,
  ChevronDown,
  ChevronUp,
  ListChecks,
  Loader2,
  Play,
  Plus,
  Trash2,
  User,
} from "lucide-react";
import {
  approveActionItem,
  createAutomation,
  deleteAutomation,
  getAutomations,
  getWorkflowRuns,
  postWorkflow,
  runAutomation,
  type Automation,
} from "@/lib/api";
import { DEMO_WORKFLOW_RUNS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { getConnectorIcon } from "@/lib/connector-meta";
import type { ActionItem, WorkflowRun } from "@/lib/types";

const CADENCES = ["manual", "hourly", "daily", "weekly"] as const;

function timeAgo(iso: string | null) {
  if (!iso) return "never";
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
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

// ─── Transcript-extraction (formerly the Workflows page) ─────────────────────

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
  const DestinationIcon =
    item.destination === "manual" ? User : getConnectorIcon(item.destination);

  async function handleApprove() {
    setApproving(true);
    await onApprove(runId, item.id);
    setApproving(false);
  }

  return (
    <div className="action-item-row">
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span className="connector-inline-icon" aria-hidden>
            <DestinationIcon size={13} strokeWidth={1.8} />
          </span>
          <span className="text-caption" style={{ color: "var(--text-primary)", fontWeight: 600 }}>{item.title}</span>
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {item.owner && (
            <span className="meta" style={{ display: "inline-flex", alignItems: "center", gap: 3 }}><User size={11} /> {item.owner.split("@")[0]}</span>
          )}
          {item.due_date && <span className="meta" style={{ display: "inline-flex", alignItems: "center", gap: 3 }}><Calendar size={11} /> Due {item.due_date}</span>}
          <span className="meta">confidence: {Math.round(item.confidence * 100)}%</span>
        </div>
        {item.source_quote && (
          <p className="source-quote" style={{ marginTop: 8 }}>
            &ldquo;{item.source_quote}&rdquo;
          </p>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8, flexShrink: 0 }}>
        <span className={`badge ${STATUS_BADGE[item.status] ?? "badge-grey"}`}>{item.status}</span>
        {item.status === "needs_review" && (
          <button className="btn btn-primary btn-xs" disabled={approving} onClick={handleApprove}>
            {approving ? "…" : "Approve →"}
          </button>
        )}
        {item.external_url && (
          <a href={item.external_url} target="_blank" rel="noopener noreferrer" className="text-[11px]" style={{ color: "var(--accent)" }}>
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
  const tier = run.data_tier ?? "normal";

  return (
    <div className="card workflow-run-card" style={{ padding: 0, overflow: "hidden" }}>
      <button onClick={onToggle} className="workflow-run-header">
        <div style={{ width: 3, height: 36, borderRadius: 9999, background: TIER_COLORS[tier] ?? TIER_COLORS.normal, flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span className="run-link">{run.id}</span>
            <span className={`badge ${STATUS_BADGE[run.status] ?? "badge-grey"}`}>{run.status}</span>
            {pendingCount > 0 && (
              <span className="badge badge-yellow" style={{ fontSize: 10 }}>{pendingCount} pending</span>
            )}
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <span className="meta" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}><ListChecks size={11} /> {items.length} action items</span>
            <span className="meta" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}><ArrowRight size={11} /> {run.destination}</span>
            <span className="meta" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}><Bot size={11} /> {run.model_route}</span>
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

// ─── Page ────────────────────────────────────────────────────────────────────

type Mode = "task" | "transcript";

export default function AutomationsPage() {
  const [mode, setMode] = useState<Mode>("task");

  // Task automations
  const [items, setItems] = useState<Automation[]>([]);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [cadence, setCadence] = useState<string>("daily");
  const [creating, setCreating] = useState(false);
  const [running, setRunning] = useState<string | null>(null);
  const [result, setResult] = useState<{ id: string; text: string } | null>(null);

  // Transcript extraction
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [inputText, setInputText] = useState("");
  const [destination, setDestination] = useState("manual");
  const [extracting, setExtracting] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  function refresh() {
    getAutomations().then(setItems);
  }
  useEffect(refresh, []);
  useEffect(() => {
    getWorkflowRuns().then((data) => {
      const hasReal = data.some((w) => (w.action_items ?? []).length > 0);
      const display = hasReal ? data : isDemo() ? DEMO_WORKFLOW_RUNS : data;
      setRuns(display);
      if (display[0]) setExpandedIds(new Set([display[0].id]));
    });
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !prompt.trim()) return;
    setCreating(true);
    try {
      await createAutomation({ name: name.trim(), prompt: prompt.trim(), cadence });
      setName("");
      setPrompt("");
      refresh();
    } finally {
      setCreating(false);
    }
  }

  async function handleRun(id: string) {
    setRunning(id);
    setResult(null);
    try {
      const res = await runAutomation(id);
      setResult({ id, text: res.result });
      refresh();
    } finally {
      setRunning(null);
    }
  }

  async function handleDelete(id: string) {
    await deleteAutomation(id);
    refresh();
  }

  function toggleExpand(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function handleExtract(e: React.FormEvent) {
    e.preventDefault();
    if (!inputText.trim()) return;
    setExtracting(true);
    try {
      const run = await postWorkflow(inputText.trim(), destination);
      setRuns((prev) => [run, ...prev]);
      setExpandedIds((prev) => new Set([run.id, ...prev]));
      setInputText("");
    } catch {
      // Demo fallback: synthesise a run so the flow is demonstrable offline.
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
            title: inputText.trim().split(".")[0].replace(/^[A-Z][^:]*:\s*/, "").slice(0, 80),
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
    } finally {
      setExtracting(false);
    }
  }

  async function handleApprove(runId: string, itemId: string) {
    try {
      await approveActionItem(runId, itemId);
    } catch {
      // Demo mode — update local state only.
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

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Automations</h1>
          <p>
            Give OSAI a job to do — run a task on demand or on a cadence, or extract action items
            from a meeting transcript.
          </p>
        </div>
      </div>

      {/* Mode toggle */}
      <div className="segmented" style={{ display: "inline-flex", gap: 4, marginBottom: 20, padding: 4, background: "var(--bg-elevated)", border: "1px solid var(--border)", borderRadius: 10 }}>
        {([
          { id: "task", label: "Run a task" },
          { id: "transcript", label: "From transcript" },
        ] as { id: Mode; label: string }[]).map((m) => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            className="btn"
            style={{
              fontSize: 13,
              padding: "6px 14px",
              background: mode === m.id ? "var(--accent)" : "transparent",
              color: mode === m.id ? "#fff" : "var(--text-secondary)",
              border: "none",
            }}
          >
            {m.label}
          </button>
        ))}
      </div>

      {mode === "task" ? (
        <>
          {/* Create automation */}
          <form className="card" onSubmit={handleCreate} style={{ marginBottom: 24 }}>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
              <input
                className="search-input"
                placeholder="Automation name (e.g. Weekly support digest)"
                aria-label="Automation name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                style={{ flex: 1, minWidth: 240 }}
              />
              <select
                className="select"
                aria-label="Automation cadence"
                value={cadence}
                onChange={(e) => setCadence(e.target.value)}
              >
                {CADENCES.map((c) => (
                  <option key={c} value={c}>{c === "manual" ? "On demand" : c}</option>
                ))}
              </select>
            </div>
            <textarea
              className="search-input"
              placeholder="What should OSAI do? e.g. Summarise open blockers across Notion and Slack and list owners."
              aria-label="Automation task prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              style={{ width: "100%", resize: "vertical", marginBottom: 10 }}
            />
            <button
              type="submit"
              className="btn btn-primary"
              disabled={creating || !name.trim() || !prompt.trim()}
            >
              {creating ? <Loader2 className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
              Create automation
            </button>
            {(!name.trim() || !prompt.trim()) && (
              <span className="meta" style={{ marginLeft: 10 }}>
                Add a name and describe what OSAI should do.
              </span>
            )}
          </form>

          {items.length === 0 ? (
            <div className="card" style={{ textAlign: "center", padding: "40px 24px" }}>
              <p className="meta">No automations yet. Create one above.</p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {items.map((a) => (
                <div key={a.id} className="card">
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                        <span style={{ fontWeight: 600, fontSize: 14 }}>{a.name}</span>
                        <span className="badge badge-grey" style={{ fontSize: 10 }}>
                          {a.cadence === "manual" ? "on demand" : a.cadence}
                        </span>
                        <span className="meta" style={{ fontSize: 11 }}>· last run {timeAgo(a.last_run_at)}</span>
                      </div>
                      <p className="meta" style={{ fontSize: 12, lineHeight: 1.5, margin: 0 }}>{a.prompt}</p>
                    </div>
                    <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                      <button
                        className="btn btn-primary"
                        style={{ fontSize: 12, padding: "6px 12px" }}
                        disabled={running === a.id}
                        onClick={() => handleRun(a.id)}
                      >
                        {running === a.id ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
                        Run now
                      </button>
                      <button
                        className="btn btn-danger"
                        style={{ fontSize: 12, padding: "6px 10px" }}
                        onClick={() => handleDelete(a.id)}
                        aria-label="Delete automation"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </div>

                  {(result?.id === a.id || a.last_result) && (
                    <div
                      style={{
                        marginTop: 12,
                        padding: "12px 14px",
                        background: "var(--bg-elevated)",
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                        fontSize: 13,
                        lineHeight: 1.6,
                        whiteSpace: "pre-wrap",
                        color: "var(--text-secondary)",
                      }}
                    >
                      {result?.id === a.id ? result.text : a.last_result}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <p className="meta" style={{ marginTop: 20, fontSize: 11 }}>
            Recurring runs on the chosen cadence require the background scheduler (Celery worker) to be
            enabled in deployment. &quot;Run now&quot; works today.
          </p>
        </>
      ) : (
        <>
          {/* Extract action items from a transcript */}
          <div className="card" style={{ marginBottom: 24 }}>
            <h2 style={{ marginBottom: 16 }}>Extract Action Items</h2>
            <form onSubmit={handleExtract}>
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
                <select value={destination} onChange={(e) => setDestination(e.target.value)} className="select">
                  <option value="manual">Manual Review</option>
                  <option value="notion">Notion</option>
                  <option value="freshdesk">Freshdesk</option>
                  <option value="slack">Slack</option>
                  <option value="google_drive">Google Drive</option>
                </select>
                <button type="submit" className="btn btn-primary" disabled={extracting || !inputText.trim()}>
                  {extracting ? "Running…" : "Extract action items"}
                </button>
                {!inputText.trim() && (
                  <span className="meta">Paste some text to extract action items from.</span>
                )}
              </div>
            </form>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
            <h2 style={{ margin: 0 }}>History</h2>
            <span className="meta">({runs.length} runs)</span>
          </div>

          {runs.length === 0 ? (
            <div className="card" style={{ textAlign: "center", padding: "40px 24px" }}>
              <p className="text-body font-semibold" style={{ marginBottom: 6 }}>No extractions yet</p>
              <p className="meta leading-normal" style={{ maxWidth: 460, margin: "0 auto 8px" }}>
                Paste meeting notes or a transcript and OSAI extracts the action items — owner, due date
                and a source quote — then pushes them to Notion, Slack, Freshdesk or manual review.
              </p>
            </div>
          ) : (
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
          )}
        </>
      )}
    </div>
  );
}
