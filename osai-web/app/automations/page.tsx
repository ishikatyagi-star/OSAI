"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Bot,
  Calendar,
  ChevronDown,
  ChevronUp,
  ListChecks,
  Loader2,
  Pencil,
  Play,
  Plus,
  Sparkles,
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
  mintAutomationToken,
  revokeAutomationToken,
  runAutomation,
  updateAutomation,
  type Automation,
} from "@/lib/api";
import { DEMO_WORKFLOW_RUNS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { getConnectorIcon } from "@/lib/connector-meta";
import type { ActionItem, WorkflowRun } from "@/lib/types";
import { Select } from "@/components/ui/select";
import { brandText, timeAgo } from "@/lib/utils";
import { SheldonMascot } from "@/components/sheldon-mascot";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const CADENCES = ["manual", "hourly", "daily", "weekly"] as const;
const CADENCE_OPTIONS = CADENCES.map((value) => ({
  value,
  label: value === "manual" ? "On demand" : `${value} (scheduler required)`,
  disabled: value !== "manual",
}));

const DEMO_AUTOMATIONS: Automation[] = [
  {
    id: "automation-support-digest",
    name: "Support blocker digest",
    prompt: "Summarize unresolved Freshdesk tickets and name the owner of each blocker.",
    cadence: "manual",
    enabled: true,
    status: "active",
    last_run_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    last_result: "3 blockers found across onboarding, billing, and SSO. Owners are listed in the latest run.",
    deliver_to: null,
    last_delivery: null,
    updated_at: new Date().toISOString(),
    has_trigger_token: false,
  },
  {
    id: "automation-roadmap-risks",
    name: "Roadmap risk check",
    prompt: "Compare Notion roadmap commitments with current Slack status updates and flag drift.",
    cadence: "manual",
    enabled: true,
    status: "active",
    last_run_at: new Date(Date.now() - 22 * 60 * 60 * 1000).toISOString(),
    last_result: "Two roadmap items have no matching status update this week.",
    deliver_to: null,
    last_delivery: null,
    updated_at: new Date().toISOString(),
    has_trigger_token: false,
  },
  {
    id: "automation-meeting-followup",
    name: "Meeting follow-up review",
    prompt: "Collect unassigned meeting actions and prepare a review list.",
    cadence: "manual",
    enabled: true,
    status: "paused",
    last_run_at: null,
    last_result: null,
    deliver_to: null,
    last_delivery: null,
    updated_at: new Date().toISOString(),
    has_trigger_token: false,
  },
];


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
  onApprove: (runId: string, itemId: string) => Promise<boolean>;
}) {
  const [approving, setApproving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [approvalError, setApprovalError] = useState("");
  const DestinationIcon =
    item.destination === "manual" ? User : getConnectorIcon(item.destination);

  async function handleApprove() {
    if (approving) return;
    setApproving(true);
    setApprovalError("");
    const approved = await onApprove(runId, item.id);
    setApproving(false);
    if (approved) setConfirming(false);
    else setApprovalError("The action was not approved or executed. Check the destination and try again.");
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
        {["needs_review", "failed"].includes(item.status) && (
          <button
            type="button"
            className="btn btn-primary btn-xs"
            disabled={approving}
            onClick={() => setConfirming(true)}
            aria-label={`Approve and execute: ${brandText(item.title)}`}
          >
            {approving ? "…" : item.status === "failed" ? "Retry →" : "Approve →"}
          </button>
        )}
        {item.external_url && (
          <a href={item.external_url} target="_blank" rel="noopener noreferrer" className="text-[11px]" style={{ color: "var(--accent)" }}>
            View →
          </a>
        )}
      </div>
      <Dialog open={confirming} onOpenChange={(open) => !approving && setConfirming(open)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve this action?</DialogTitle>
            <DialogDescription>
              “{brandText(item.title)}” will be sent to {brandText(item.destination)}. Review the owner and destination before continuing.
            </DialogDescription>
          </DialogHeader>
          {approvalError && <p className="error-text" role="alert">{approvalError}</p>}
          <DialogFooter>
            <button type="button" className="btn" onClick={() => setConfirming(false)} disabled={approving}>Cancel</button>
            <button type="button" className="btn btn-primary" onClick={handleApprove} disabled={approving}>
              {approving ? "Approving…" : "Approve action"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
  onApprove: (runId: string, itemId: string) => Promise<boolean>;
}) {
  const items = run.action_items ?? [];
  const pendingCount = items.filter((a) => a.status === "needs_review").length;
  const tier = run.data_tier ?? "normal";

  return (
    <div className="card workflow-run-card" style={{ padding: 0, overflow: "hidden" }}>
      <button
        type="button"
        onClick={onToggle}
        className="workflow-run-header"
        aria-expanded={expanded}
        aria-controls={`automation-run-${run.id}`}
      >
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
        <div id={`automation-run-${run.id}`} style={{ borderTop: "1px solid var(--border)", padding: "0 22px 18px" }}>
          {items.map((item) => (
            <ActionItemRow key={item.id} item={item} runId={run.id} onApprove={onApprove} />
          ))}
        </div>
      )}
      {expanded && items.length === 0 && (
        <div id={`automation-run-${run.id}`} style={{ padding: "12px 22px 18px", borderTop: "1px solid var(--border)" }}>
          <p className="meta">No action items extracted from this run.</p>
        </div>
      )}

    </div>
  );
}

// ─── Edit automation (PATCH) ─────────────────────────────────────────────────

function EditAutomationForm({
  automation,
  onSaved,
  onCancel,
}: {
  automation: Automation;
  onSaved: (updated?: Automation) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(automation.name);
  const [prompt, setPrompt] = useState(automation.prompt);
  const [cadence, setCadence] = useState<string>(automation.cadence);
  const [status, setStatus] = useState<string>(automation.status ?? "active");
  const [slackTarget, setSlackTarget] = useState<string>(
    automation.deliver_to?.channel === "slack" ? automation.deliver_to.target : ""
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !prompt.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const patch: Parameters<typeof updateAutomation>[1] = {
        name: name.trim(),
        prompt: prompt.trim(),
        cadence: cadence as Automation["cadence"],
        status: status as Automation["status"],
        // Empty input clears delivery ({}), a channel name sets it.
        deliver_to: slackTarget.trim()
          ? { channel: "slack", target: slackTarget.trim() }
          : {},
      };
      if (isDemo()) {
        onSaved({
          ...automation,
          ...patch,
          deliver_to: slackTarget.trim()
            ? { channel: "slack", target: slackTarget.trim() }
            : null,
          updated_at: new Date().toISOString(),
        });
      } else {
        await updateAutomation(automation.id, patch);
        onSaved();
      }
    } catch {
      setError("Couldn't save changes. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="automation-edit-form" onSubmit={handleSave} style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
      <div className="automation-form-row">
        <input
          className="search-input"
          aria-label="Automation name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ flex: 1, minWidth: 0 }}
        />
        <Select
          aria-label="Automation cadence"
          value={cadence}
          onValueChange={setCadence}
          options={CADENCE_OPTIONS}
        />
        <Select
          aria-label="Automation status"
          value={status}
          onValueChange={setStatus}
          options={[
            { value: "active", label: "active" },
            { value: "paused", label: "paused" },
            { value: "draft", label: "draft" },
          ]}
        />
      </div>
      <textarea
        className="search-input"
        aria-label="Automation task prompt"
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={3}
        style={{ width: "100%", resize: "vertical", marginBottom: 10 }}
      />
      <label className="meta automation-delivery-field">
        Deliver results to Slack channel
        <input
          className="search-input"
          aria-label="Slack channel for results"
          placeholder="#general (empty = dashboard only)"
          value={slackTarget}
          onChange={(e) => setSlackTarget(e.target.value)}
          style={{ flex: 1, minWidth: 0 }}
        />
      </label>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button type="submit" className="btn btn-primary" style={{ fontSize: 12 }} disabled={saving || !name.trim() || !prompt.trim()}>
          {saving ? <Loader2 className="size-3.5 animate-spin" /> : null}
          Save changes
        </button>
        <button type="button" className="btn" style={{ fontSize: 12 }} onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        {error && <span className="meta" style={{ color: "var(--red)" }}>{error}</span>}
      </div>
    </form>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

type Mode = "task" | "transcript";
type OperationKind = "run" | "mint" | "revoke" | "delete";

export default function AutomationsPage() {
  const [mode, setMode] = useState<Mode>("task");

  // Task automations
  const [items, setItems] = useState<Automation[]>([]);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [cadence, setCadence] = useState<string>("manual");
  const [automationLoading, setAutomationLoading] = useState(true);
  const [automationLoadError, setAutomationLoadError] = useState("");
  const [creating, setCreating] = useState(false);
  const pendingOpsRef = useRef(new Set<string>());
  const [pendingOps, setPendingOps] = useState<Record<string, true>>({});
  const [result, setResult] = useState<{ id: string; text: string } | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  // Freshly minted trigger token, shown once per mint (never re-fetchable).
  const [minted, setMinted] = useState<{ id: string; token: string } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Automation | null>(null);
  const [pendingRevoke, setPendingRevoke] = useState<Automation | null>(null);
  const [mutationError, setMutationError] = useState("");

  function operationKey(kind: OperationKind, id: string) {
    return `${kind}:${id}`;
  }

  function beginOperation(kind: OperationKind, id: string) {
    const key = operationKey(kind, id);
    if (Array.from(pendingOpsRef.current).some((pendingKey) => pendingKey.endsWith(`:${id}`))) return false;
    pendingOpsRef.current.add(key);
    setPendingOps((current) => ({ ...current, [key]: true }));
    return true;
  }

  function finishOperation(kind: OperationKind, id: string) {
    const key = operationKey(kind, id);
    pendingOpsRef.current.delete(key);
    setPendingOps((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function isOperationPending(kind: OperationKind, id: string) {
    return Boolean(pendingOps[operationKey(kind, id)]);
  }

  function isAutomationBusy(id: string) {
    return Object.keys(pendingOps).some((key) => key.endsWith(`:${id}`));
  }

  function hasPendingKind(kind: OperationKind) {
    return Array.from(pendingOpsRef.current).some((key) => key.startsWith(`${kind}:`));
  }

  const anyRunPending = Object.keys(pendingOps).some((key) => key.startsWith("run:"));

  async function handleMintToken(id: string) {
    setMutationError("");
    if (isDemo()) {
      setMutationError("API trigger tokens are disabled in the shared demo workspace.");
      return;
    }
    if (!beginOperation("mint", id)) return;
    try {
      const res = await mintAutomationToken(id);
      setMinted({ id, token: res.token });
      setItems((current) => current.map((item) => item.id === id ? { ...item, has_trigger_token: true } : item));
    } catch {
      setMutationError("The API trigger token could not be created. Please try again.");
    } finally {
      finishOperation("mint", id);
    }
  }

  async function handleRevokeToken(id: string) {
    if (!beginOperation("revoke", id)) return;
    setMutationError("");
    try {
      await revokeAutomationToken(id);
      setMinted((m) => (m?.id === id ? null : m));
      setPendingRevoke(null);
      refresh();
    } catch {
      setMutationError("The API trigger token could not be revoked. Please try again.");
    } finally {
      finishOperation("revoke", id);
    }
  }

  // Transcript extraction
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);
  const [runsLoadError, setRunsLoadError] = useState("");
  const [inputText, setInputText] = useState("");
  const [destination, setDestination] = useState("manual");
  const [extracting, setExtracting] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  function refresh() {
    if (isDemo()) {
      setItems(DEMO_AUTOMATIONS);
      setAutomationLoading(false);
      return;
    }
    setAutomationLoading(true);
    setAutomationLoadError("");
    getAutomations(true)
      .then(setItems)
      .catch(() => setAutomationLoadError("Automations could not be loaded. Check your connection and retry."))
      .finally(() => setAutomationLoading(false));
  }
  useEffect(refresh, []);
  useEffect(() => {
    if (isDemo()) {
      setRuns(DEMO_WORKFLOW_RUNS);
      setExpandedIds(new Set([DEMO_WORKFLOW_RUNS[0].id]));
      setRunsLoading(false);
      return;
    }
    setRunsLoading(true);
    setRunsLoadError("");
    getWorkflowRuns(true).then((data) => {
      const hasReal = data.some((w) => (w.action_items ?? []).length > 0);
      const display = hasReal ? data : isDemo() ? DEMO_WORKFLOW_RUNS : data;
      setRuns(display);
      if (display[0]) setExpandedIds(new Set([display[0].id]));
    }).catch(() => setRunsLoadError("Workflow history could not be loaded. Check your connection and retry."))
      .finally(() => setRunsLoading(false));
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !prompt.trim()) return;
    setCreating(true);
    setMutationError("");
    try {
      if (isDemo()) {
        const created: Automation = {
          id: `automation-demo-${Date.now()}`,
          name: name.trim(),
          prompt: prompt.trim(),
          cadence: "manual",
          enabled: true,
          status: "active",
          last_run_at: null,
          last_result: null,
          deliver_to: null,
          last_delivery: null,
          updated_at: new Date().toISOString(),
          has_trigger_token: false,
        };
        setItems((prev) => [created, ...prev]);
      } else {
        await createAutomation({ name: name.trim(), prompt: prompt.trim(), cadence });
        refresh();
      }
      setName("");
      setPrompt("");
    } catch {
      setMutationError("The automation could not be created. Please try again.");
    } finally {
      setCreating(false);
    }
  }

  async function handleRun(id: string) {
    if (hasPendingKind("run") || !beginOperation("run", id)) return;
    setResult(null);
    setMutationError("");
    try {
      if (isDemo()) {
        const text = "Demo run complete. Sheldon found two items that need an owner and one status update that is overdue.";
        setResult({ id, text });
        setItems((prev) => prev.map((item) => item.id === id ? { ...item, last_run_at: new Date().toISOString(), last_result: text } : item));
      } else {
        const res = await runAutomation(id);
        setResult({ id, text: res.result });
        refresh();
      }
    } catch {
      setMutationError("The automation did not run. No result was saved; please try again.");
    } finally {
      finishOperation("run", id);
    }
  }

  async function handleDelete(id: string) {
    if (!beginOperation("delete", id)) return;
    setMutationError("");
    try {
      if (!isDemo()) await deleteAutomation(id);
      setItems((prev) => prev.filter((item) => item.id !== id));
      setPendingDelete(null);
    } catch {
      setMutationError("The automation could not be deleted. Please try again.");
    } finally {
      finishOperation("delete", id);
    }
  }

  function toggleExpand(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function handleModeKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, current: Mode) {
    const modes: Mode[] = ["task", "transcript"];
    const index = modes.indexOf(current);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % modes.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + modes.length) % modes.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = modes.length - 1;
    else return;
    event.preventDefault();
    const nextMode = modes[next];
    setMode(nextMode);
    requestAnimationFrame(() => document.getElementById(`automation-tab-${nextMode}`)?.focus());
  }

  async function handleExtract(e: React.FormEvent) {
    e.preventDefault();
    if (!inputText.trim()) return;
    setExtracting(true);
    try {
      if (isDemo()) {
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
        return;
      }
      const run = await postWorkflow(inputText.trim(), destination);
      setRuns((prev) => [run, ...prev]);
      setExpandedIds((prev) => new Set([run.id, ...prev]));
      setInputText("");
    } catch {
      setMutationError("Action items could not be extracted. No run was created; please try again.");
    } finally {
      setExtracting(false);
    }
  }

  async function handleApprove(runId: string, itemId: string) {
    let nextStatus = "approved";
    let externalUrl: string | null = null;
    try {
      if (!isDemo()) {
        const approval = await approveActionItem(runId, itemId);
        nextStatus = approval.status;
        externalUrl = approval.external_url;
      }
    } catch {
      setMutationError("The action was not approved or executed. Please try again.");
      return false;
    }
    setRuns((prev) =>
      prev.map((r) =>
        r.id !== runId
          ? r
          : {
              ...r,
              action_items: (r.action_items ?? []).map((a) =>
                a.id === itemId ? { ...a, status: nextStatus, external_url: externalUrl ?? a.external_url } : a
              ),
            }
      )
    );
    if (nextStatus === "failed") {
      setMutationError("The destination rejected the action. Review the connection and retry execution.");
      return false;
    }
    return true;
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Automations</h1>
          <p>
            Give Sheldon a job to do - run a task on demand or on a cadence, or extract action items
            from a meeting transcript.
          </p>
        </div>
      </div>

      {/* Mode toggle */}
      <div className="segmented" role="tablist" aria-label="Automation modes" style={{ display: "inline-flex", gap: 4, marginBottom: 20, padding: 4, background: "var(--bg-elevated)", border: "1px solid var(--border)", borderRadius: 10 }}>
        {([
          { id: "task", label: "Run a task" },
          { id: "transcript", label: "From transcript" },
        ] as { id: Mode; label: string }[]).map((m) => (
          <button
            key={m.id}
            type="button"
            onClick={() => setMode(m.id)}
            onKeyDown={(event) => handleModeKeyDown(event, m.id)}
            className="btn"
            role="tab"
            id={`automation-tab-${m.id}`}
            aria-selected={mode === m.id}
            aria-controls={`automation-panel-${m.id}`}
            tabIndex={mode === m.id ? 0 : -1}
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

      {mutationError && (
        <div className="card" role="alert" style={{ marginBottom: 16, padding: "10px 14px", color: "var(--red)" }}>
          {mutationError}
        </div>
      )}

      {mode === "task" ? (
        <div role="tabpanel" id="automation-panel-task" aria-labelledby="automation-tab-task">
          {/* Create conversationally: Sheldon asks clarifying questions in chat and
              creates the automation itself once the goal, sources and cadence are clear. */}
          <div className="card" style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <Sparkles className="size-4" style={{ color: "var(--accent)", flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 220 }}>
              <span style={{ fontWeight: 600, fontSize: 13 }}>Create with Sheldon</span>
              <p className="meta" style={{ fontSize: 12, margin: 0 }}>
                Describe the job in chat - Sheldon asks what it needs, then sets up the automation for you.
              </p>
            </div>
            <Link
              href={`/ask?q=${encodeURIComponent("Set up an automation: ")}`}
              className="btn btn-primary"
              style={{ fontSize: 12, padding: "6px 14px", flexShrink: 0 }}
            >
              Open chat →
            </Link>
          </div>

          {/* Create automation (manual form) */}
          <form className="card" onSubmit={handleCreate} style={{ marginBottom: 24 }}>
            <div className="automation-form-row">
              <input
                className="search-input"
                placeholder="Automation name (e.g. Weekly support digest)"
                aria-label="Automation name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                style={{ flex: 1, minWidth: 0 }}
              />
              <Select
                aria-label="Automation cadence"
                value={cadence}
                onValueChange={setCadence}
                options={CADENCE_OPTIONS}
              />
            </div>
            {cadence !== "manual" && (
              <p className="meta" style={{ marginBottom: 10, fontSize: 11, color: "var(--amber, var(--text-secondary))" }}>
                Recurring cadences are not firing automatically in this deployment yet - they need the
                background scheduler. Until then, run this automation with &quot;Run now&quot;.
              </p>
            )}
            <textarea
              className="search-input"
              placeholder="What should Sheldon do? e.g. Summarise open blockers across Notion and Slack and list owners."
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
                Add a name and describe what Sheldon should do.
              </span>
            )}
          </form>

          {automationLoadError ? (
            <div className="card async-state" role="alert">
              <div>
                <p className="error-text" style={{ marginBottom: 12 }}>{automationLoadError}</p>
                <button type="button" className="btn btn-primary" onClick={refresh}>Retry</button>
              </div>
            </div>
          ) : automationLoading ? (
            <div className="card async-state" role="status" aria-live="polite">
              <Loader2 className="size-5 animate-spin" aria-hidden="true" /> Loading automations…
            </div>
          ) : items.length === 0 ? (
            <div className="card" style={{ textAlign: "center", padding: "40px 24px" }}>
              <SheldonMascot state="orchestrating" size={96} className="empty-state-mascot" />
              <p className="meta">No automations yet. Create one above.</p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {items.map((a) => (
                <div key={a.id} className="card">
                  <div className="automation-card-header">
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
                        <span style={{ fontWeight: 600, fontSize: 14 }}>{brandText(a.name)}</span>
                        <span className="badge badge-grey" style={{ fontSize: 10 }}>
                          {a.cadence === "manual" ? "on demand" : a.cadence}
                        </span>
                        {a.status && a.status !== "active" && (
                          <span className={`badge ${a.status === "paused" ? "badge-yellow" : "badge-grey"}`} style={{ fontSize: 10 }}>
                            {a.status}
                          </span>
                        )}
                        <span className="meta" style={{ fontSize: 11 }}>· last run {timeAgo(a.last_run_at)}</span>
                        {a.deliver_to?.channel === "slack" && (
                          <span
                            className="meta"
                            style={{
                              fontSize: 11,
                              color:
                                a.last_delivery?.status === "failed"
                                  ? "var(--red)"
                                  : undefined,
                            }}
                          >
                            {a.last_delivery?.status === "failed"
                              ? `· delivery to ${a.deliver_to.target} failed`
                              : `· delivers to ${a.deliver_to.target}`}
                          </span>
                        )}
                      </div>
                      <p className="meta" style={{ fontSize: 12, lineHeight: 1.5, margin: 0 }}>{brandText(a.prompt)}</p>
                      {minted?.id === a.id && (
                        <div
                          className="card"
                          style={{ marginTop: 8, padding: "8px 12px", fontSize: 11 }}
                        >
                          <p style={{ margin: 0, fontWeight: 600 }}>
                            Trigger token (copy now - shown once):
                          </p>
                          <code style={{ wordBreak: "break-all" }}>{minted.token}</code>
                          <p className="meta" style={{ margin: "6px 0 0", fontSize: 11 }}>
                            {`curl -X POST -H "X-Trigger-Token: ${minted.token.slice(0, 12)}…" $API/automations/${a.id}/trigger`}
                          </p>
                        </div>
                      )}
                    </div>
                    <div className="automation-card-actions">
                      <button
                        className="btn btn-primary"
                        style={{ fontSize: 12, padding: "6px 12px" }}
                        disabled={anyRunPending || isAutomationBusy(a.id) || editingId === a.id}
                        onClick={() => handleRun(a.id)}
                        aria-label={`Run automation now: ${brandText(a.name)}`}
                      >
                        {isOperationPending("run", a.id) ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
                        Run now
                      </button>
                      <button
                        className="btn"
                        style={{ fontSize: 12, padding: "6px 10px" }}
                        disabled={isAutomationBusy(a.id) || editingId === a.id}
                        onClick={() => setEditingId(editingId === a.id ? null : a.id)}
                        aria-label={`Edit automation: ${brandText(a.name)}`}
                      >
                        <Pencil className="size-3.5" />
                      </button>
                      <button
                        className="btn"
                        style={{ fontSize: 12, padding: "6px 10px" }}
                        title={
                          a.has_trigger_token
                            ? "Rotate or revoke the API trigger token"
                            : "Create an API trigger token"
                        }
                        disabled={isAutomationBusy(a.id) || editingId === a.id}
                        onClick={() => {
                          setMutationError("");
                          if (a.has_trigger_token) setPendingRevoke(a);
                          else void handleMintToken(a.id);
                        }}
                        aria-label={a.has_trigger_token ? `Revoke API trigger token for ${brandText(a.name)}` : `Create API trigger token for ${brandText(a.name)}`}
                      >
                        {isOperationPending("mint", a.id) ? <Loader2 className="size-3.5 animate-spin" /> : a.has_trigger_token ? "API ✓" : "API"}
                      </button>
                      <Link
                        href={`/ask?q=${encodeURIComponent(`Update automation ${a.id} ("${a.name}"): `)}`}
                        className="btn"
                        style={{ fontSize: 12, padding: "6px 10px" }}
                        aria-label={`Refine automation with Sheldon: ${brandText(a.name)}`}
                        title="Refine with Sheldon"
                        aria-disabled={isAutomationBusy(a.id) || editingId === a.id}
                        onClick={(event) => {
                          if (isAutomationBusy(a.id) || editingId === a.id) event.preventDefault();
                        }}
                      >
                        <Sparkles className="size-3.5" />
                      </Link>
                      <button
                        className="btn btn-danger"
                        style={{ fontSize: 12, padding: "6px 10px" }}
                        disabled={isAutomationBusy(a.id) || editingId === a.id}
                        onClick={() => { setMutationError(""); setPendingDelete(a); }}
                        aria-label={`Delete automation: ${brandText(a.name)}`}
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </div>

                  {editingId === a.id && (
                    <EditAutomationForm
                      automation={a}
                      onSaved={(updated) => {
                        if (updated) setItems((prev) => prev.map((item) => item.id === updated.id ? updated : item));
                        setEditingId(null);
                        if (!isDemo()) refresh();
                      }}
                      onCancel={() => setEditingId(null)}
                    />
                  )}

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
                      {brandText(result?.id === a.id ? result.text : a.last_result ?? "")}
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
        </div>
      ) : (
        <div role="tabpanel" id="automation-panel-transcript" aria-labelledby="automation-tab-transcript">
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
                <Select
                  aria-label="Action item destination"
                  value={destination}
                  onValueChange={setDestination}
                  options={[
                    { value: "manual", label: "Manual Review" },
                    { value: "notion", label: "Notion" },
                    { value: "freshdesk", label: "Freshdesk" },
                    { value: "slack", label: "Slack" },
                    { value: "google_drive", label: "Google Drive" },
                  ]}
                />
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

          {runsLoadError ? (
            <div className="card async-state" role="alert">
              <p className="error-text">{runsLoadError}</p>
            </div>
          ) : runsLoading ? (
            <div className="card async-state" role="status" aria-live="polite">
              <Loader2 className="size-5 animate-spin" aria-hidden="true" /> Loading workflow history…
            </div>
          ) : runs.length === 0 ? (
            <div className="card" style={{ textAlign: "center", padding: "40px 24px" }}>
              <p className="text-body font-semibold" style={{ marginBottom: 6 }}>No extractions yet</p>
              <p className="meta leading-normal" style={{ maxWidth: 460, margin: "0 auto 8px" }}>
                Paste meeting notes or a transcript and Sheldon extracts the action items - owner, due date
                and a source quote - then pushes them to Notion, Slack, Freshdesk or manual review.
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
        </div>
      )}

      {pendingDelete && (
        <Dialog open onOpenChange={(open) => !open && !isOperationPending("delete", pendingDelete.id) && setPendingDelete(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete this automation?</DialogTitle>
              <DialogDescription>
                “{brandText(pendingDelete.name)}” will be permanently removed. Existing run history will not be recreated.
              </DialogDescription>
            </DialogHeader>
            {mutationError && <p className="error-text" role="alert">{mutationError}</p>}
            <DialogFooter>
              <button type="button" className="btn" onClick={() => setPendingDelete(null)} disabled={isOperationPending("delete", pendingDelete.id)}>Cancel</button>
              <button type="button" className="btn btn-danger" onClick={() => handleDelete(pendingDelete.id)} disabled={isOperationPending("delete", pendingDelete.id)}>
                {isOperationPending("delete", pendingDelete.id) ? "Deleting…" : "Delete automation"}
              </button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {pendingRevoke && (
        <Dialog open onOpenChange={(open) => !open && !isOperationPending("revoke", pendingRevoke.id) && setPendingRevoke(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Revoke the API trigger token?</DialogTitle>
              <DialogDescription>
                API calls using the current token for “{brandText(pendingRevoke.name)}” will stop working immediately.
              </DialogDescription>
            </DialogHeader>
            {mutationError && <p className="error-text" role="alert">{mutationError}</p>}
            <DialogFooter>
              <button type="button" className="btn" onClick={() => setPendingRevoke(null)} disabled={isOperationPending("revoke", pendingRevoke.id)}>Cancel</button>
              <button type="button" className="btn btn-danger" onClick={() => handleRevokeToken(pendingRevoke.id)} disabled={isOperationPending("revoke", pendingRevoke.id)}>
                {isOperationPending("revoke", pendingRevoke.id) ? "Revoking…" : "Revoke token"}
              </button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
