"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Sparkles, X } from "lucide-react";
import { DEMO_DECISIONS, type Decision } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import {
  createDecision,
  deleteDecision,
  getDecisions,
  updateDecision,
  type ApiDecision,
} from "@/lib/api";
import { Select } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const IMPACT_META: Record<Decision["impact"], { cls: string }> = {
  critical: { cls: "badge-red" },
  high:     { cls: "badge-blue" },
  medium:   { cls: "badge-grey" },
  low:      { cls: "badge-grey" },
};

const STATUS_META: Record<Decision["status"], { cls: string }> = {
  approved: { cls: "badge-green" },
  proposed: { cls: "badge-grey" },
  rejected: { cls: "badge-red" },
};

// Rank orders so Impact/Status sort by severity, not alphabetically.
const IMPACT_RANK: Record<Decision["impact"], number> = { critical: 0, high: 1, medium: 2, low: 3 };
const STATUS_RANK: Record<Decision["status"], number> = { proposed: 0, approved: 1, rejected: 2 };

type SortKey = "title" | "status" | "impact" | "owner" | "date";
type SortDir = "asc" | "desc";
type OwnerFilter = "all" | "mine";
type SourceFilter = "all" | "osai";
type DecisionForm = {
  id: string | null;
  title: string;
  status: Decision["status"];
  impact: Decision["impact"];
  owner: string;
  source: string;
  tags: string;
};

const EMPTY_DECISION_FORM: DecisionForm = {
  id: null,
  title: "",
  status: "proposed",
  impact: "medium",
  owner: "",
  source: "Manual",
  tags: "",
};

// First token of the signed-in user's name, used to match decisions to "me".
function myNameToken(): string {
  if (typeof window === "undefined") return "";
  const name = localStorage.getItem("osai_user_name") || "";
  return name.trim().split(/\s+/)[0]?.toLowerCase() ?? "";
}

function fromApi(row: ApiDecision): Decision {
  return {
    id: row.id,
    title: row.title,
    tags: row.tags,
    status: row.status,
    impact: row.impact,
    owner: row.owner ?? "Unassigned",
    date: new Date(row.date).toLocaleDateString("en-US", {
      day: "numeric",
      month: "short",
      year: "numeric",
    }),
    source: row.source,
    identifiedBy: row.identifiedBy,
  };
}

export default function DecisionsPage() {
  const [decisions, setDecisions] = useState<Decision[]>(() =>
    isDemo() ? DEMO_DECISIONS : []
  );
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | Decision["status"]>("all");
  const [impactFilter, setImpactFilter] = useState<"all" | Decision["impact"]>("all");
  const [ownerFilter, setOwnerFilter] = useState<OwnerFilter>("all");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [pendingDelete, setPendingDelete] = useState<Decision | null>(null);
  const [decisionForm, setDecisionForm] = useState<DecisionForm | null>(null);
  const [writeBusy, setWriteBusy] = useState(false);
  const [writeError, setWriteError] = useState("");
  const [loading, setLoading] = useState(() => !isDemo());
  const [loadError, setLoadError] = useState("");

  // Signed-in workspaces load the durable decision log from the API; demo mode
  // keeps its local fixtures (and local-only mutations below mirror that split).
  const loadDecisions = useCallback(async () => {
    if (isDemo()) {
      setDecisions(DEMO_DECISIONS);
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError("");
    try {
      const rows = await getDecisions(true);
      setDecisions(rows.map(fromApi));
    } catch {
      setLoadError("The decision log could not be loaded. Check your connection and retry.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadDecisions(); }, [loadDecisions]);

  // /board redirects here with ?source=osai - honour it as the initial filter.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("source") === "osai") setSourceFilter("osai");
  }, []);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    setWriteBusy(true);
    setWriteError("");
    try {
      if (!isDemo()) await deleteDecision(id);
      setDecisions((prev) => prev.filter((d) => d.id !== id));
      setPendingDelete(null);
    } catch {
      setWriteError("The decision could not be deleted. Please try again.");
    } finally {
      setWriteBusy(false);
    }
  }

  function openAddDecision() {
    setWriteError("");
    setDecisionForm(EMPTY_DECISION_FORM);
  }

  function openEditDecision(decision: Decision) {
    setWriteError("");
    setDecisionForm({
      id: decision.id,
      title: decision.title,
      status: decision.status,
      impact: decision.impact,
      owner: decision.owner,
      source: decision.source,
      tags: decision.tags.join(", "),
    });
  }

  async function saveDecision() {
    if (!decisionForm || decisionForm.title.trim() === "") return;
    const form = decisionForm;
    const tags = form.tags
      .split(",")
      .map((tag) => tag.trim().toLowerCase())
      .filter(Boolean);
    const nextDecision: Decision = {
      id: form.id ?? `dec-${Date.now()}`,
      title: form.title.trim(),
      tags,
      status: form.status,
      impact: form.impact,
      owner: form.owner.trim() || "Unassigned",
      date: new Date().toLocaleDateString("en-US", {
        day: "numeric",
        month: "short",
        year: "numeric",
      }),
      source: form.source.trim() || "Manual",
      identifiedBy: "source",
    };

    setWriteBusy(true);
    setWriteError("");
    try {
      if (isDemo()) {
        setDecisions((prev) =>
          form.id
            ? prev.map((decision) => (decision.id === form.id ? nextDecision : decision))
            : [nextDecision, ...prev]
        );
      } else {
        const persisted = form.id
          ? await updateDecision(form.id, {
            title: nextDecision.title,
            status: nextDecision.status,
            impact: nextDecision.impact,
            owner: nextDecision.owner,
            source: nextDecision.source,
            tags,
            })
          : await createDecision({
            title: nextDecision.title,
            status: nextDecision.status,
            impact: nextDecision.impact,
            owner: nextDecision.owner,
            source: nextDecision.source,
            tags,
            });
        const saved = fromApi(persisted);
        setDecisions((prev) =>
          form.id
            ? prev.map((decision) => (decision.id === form.id ? saved : decision))
            : [saved, ...prev]
        );
      }
      setDecisionForm(null);
    } catch {
      setWriteError("The decision could not be saved. Review your changes and try again.");
    } finally {
      setWriteBusy(false);
    }
  }

  const filtered = useMemo(() => {
    const token = myNameToken();
    const result = decisions.filter((d) => {
      const matchesSearch =
        search === "" ||
        d.title.toLowerCase().includes(search.toLowerCase()) ||
        d.tags.some((t) => t.includes(search.toLowerCase()));
      const matchesStatus = statusFilter === "all" || d.status === statusFilter;
      const matchesImpact = impactFilter === "all" || d.impact === impactFilter;
      const matchesOwner =
        ownerFilter === "all" || (token !== "" && d.owner.toLowerCase().includes(token));
      const matchesSource = sourceFilter === "all" || d.identifiedBy === "osai";
      return matchesSearch && matchesStatus && matchesImpact && matchesOwner && matchesSource;
    });

    if (sortKey) {
      const dir = sortDir === "asc" ? 1 : -1;
      result.sort((a, b) => {
        let cmp = 0;
        switch (sortKey) {
          case "title":
          case "owner":
            cmp = a[sortKey].localeCompare(b[sortKey]);
            break;
          case "impact":
            cmp = IMPACT_RANK[a.impact] - IMPACT_RANK[b.impact];
            break;
          case "status":
            cmp = STATUS_RANK[a.status] - STATUS_RANK[b.status];
            break;
          case "date":
            cmp = (Date.parse(a.date) || 0) - (Date.parse(b.date) || 0);
            break;
        }
        return cmp * dir;
      });
    }
    return result;
  }, [decisions, search, statusFilter, impactFilter, ownerFilter, sourceFilter, sortKey, sortDir]);

  const osaiCount = useMemo(
    () => decisions.filter((d) => d.identifiedBy === "osai").length,
    [decisions]
  );

  function SortableTh({ label, k, width }: { label: string; k: SortKey; width?: number }) {
    const active = sortKey === k;
    return (
      <th
        className="sortable"
        style={width ? { width } : undefined}
        aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
      >
        <button type="button" className="table-sort-button" onClick={() => toggleSort(k)}>
          {label}
          <span className={`sort-caret${active ? "" : " inactive"}`} aria-hidden="true">
            {active ? (sortDir === "asc" ? "↑" : "↓") : "↕"}
          </span>
        </button>
      </th>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Decision Log</h1>
          <p>
            Every key decision and action across your org - owned, dated, and tagged. Items Sheldon
            inferred from context but that aren&apos;t tracked in your tools are marked{" "}
            <span className="badge badge-purple" style={{ fontSize: 10 }}>Sheldon found this</span>.
          </p>
        </div>
        <button className="btn btn-primary" onClick={openAddDecision}>+ Add Decision</button>
      </div>

      {loadError && !loading && (
        <div className="card async-state" role="alert">
          <div>
            <p className="error-text" style={{ marginBottom: 12 }}>{loadError}</p>
            <button type="button" className="btn btn-primary" onClick={loadDecisions}>Retry</button>
          </div>
        </div>
      )}

      {loading && (
        <div className="card async-state" role="status" aria-live="polite">Loading decisions…</div>
      )}

      <div hidden={loading || !!loadError}>

      {/* Segmented owner / source filters (the merged Team Board lens) */}
      <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
        {([
          { key: "all", label: "All decisions" },
          { key: "mine", label: "My decisions" },
        ] as const).map((opt) => (
          <button
            key={opt.key}
            type="button"
            className={`btn btn-sm${ownerFilter === opt.key ? " btn-primary" : ""}`}
            onClick={() => setOwnerFilter(opt.key)}
            aria-pressed={ownerFilter === opt.key}
          >
            {opt.label}
          </button>
        ))}
        <button
          type="button"
          className={`btn btn-sm${sourceFilter === "osai" ? " btn-primary" : ""}`}
          onClick={() => setSourceFilter((s) => (s === "osai" ? "all" : "osai"))}
          aria-pressed={sourceFilter === "osai"}
        >
          <Sparkles className="size-3.5" /> Sheldon-identified{osaiCount > 0 ? ` (${osaiCount})` : ""}
        </button>
      </div>

      {/* Search + filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
        <input
          className="search-input"
          style={{ maxWidth: 280 }}
          placeholder="Search decisions…"
          aria-label="Search decisions"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Select
          aria-label="Filter decisions by status"
          value={statusFilter}
          onValueChange={(value) => setStatusFilter(value as typeof statusFilter)}
          options={[
            { value: "all", label: "All statuses" },
            { value: "proposed", label: "Proposed" },
            { value: "approved", label: "Approved" },
            { value: "rejected", label: "Rejected" },
          ]}
        />
        <Select
          aria-label="Filter decisions by impact level"
          value={impactFilter}
          onValueChange={(value) => setImpactFilter(value as typeof impactFilter)}
          options={[
            { value: "all", label: "All impact levels" },
            { value: "critical", label: "Critical" },
            { value: "high", label: "High" },
            { value: "medium", label: "Medium" },
            { value: "low", label: "Low" },
          ]}
        />
        <span className="meta" aria-live="polite" style={{ alignSelf: "center", marginLeft: "auto" }}>
          {filtered.length} of {decisions.length} decisions
        </span>
      </div>

      {writeError && <div className="card" role="alert" style={{ marginBottom: 16, padding: "10px 14px", color: "var(--red)" }}>{writeError}</div>}

      {/* Table */}
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Decision log">
        <table className="data-table">
        <thead>
          <tr>
            <SortableTh label="Decision" k="title" />
            <SortableTh label="Status" k="status" />
            <SortableTh label="Impact" k="impact" />
            <SortableTh label="Owner" k="owner" />
            <th>Source</th>
            <SortableTh label="Date" k="date" width={130} />
            <th style={{ width: 80 }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((d) => (
            <tr key={d.id}>
              <td>
                <div className="text-caption" style={{ marginBottom: 5, color: "var(--text-primary)", fontWeight: 600 }}>
                  {d.title}
                </div>
                <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                  {d.identifiedBy === "osai" && (
                    <span className="badge badge-purple" style={{ fontSize: 10 }}>
                      <Sparkles className="size-3" /> Sheldon found this
                    </span>
                  )}
                  {d.tags.map((t) => (
                    <span key={t} className="badge badge-grey" style={{ fontSize: 10 }}>{t}</span>
                  ))}
                </div>
              </td>
              <td>
                <span className={`badge ${STATUS_META[d.status].cls}`}>{d.status}</span>
              </td>
              <td>
                <span className={`badge ${IMPACT_META[d.impact].cls}`}>{d.impact}</span>
              </td>
              <td>
                <span className="text-micro" style={{ color: "var(--text-secondary)" }}>{d.owner}</span>
              </td>
              <td>
                <span className="meta">{d.source}</span>
              </td>
              <td>
                <span className="mono">{d.date}</span>
              </td>
              <td>
                <div style={{ display: "flex", gap: 6 }}>
                  <button
                    className="btn-ghost btn btn-xs"
                    onClick={() => openEditDecision(d)}
                    aria-label={`Edit decision: ${d.title}`}
                  >
                    Edit
                  </button>
                  <button
                    className="btn-ghost btn btn-danger btn-xs"
                    onClick={() => { setWriteError(""); setPendingDelete(d); }}
                    aria-label={`Delete decision: ${d.title}`}
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={7} style={{ textAlign: "center", color: "var(--text-muted)", padding: "32px 16px" }}>
                {decisions.length === 0
                  ? "No decisions yet. Sheldon logs decisions and surfaces uncaptured action items as it indexes your connected tools."
                  : "No decisions match this filter."}
              </td>
            </tr>
          )}
        </tbody>
        </table>
      </div>
      </div>

      {/* Add / edit decision */}
      {decisionForm && (
        <Dialog open onOpenChange={(open) => !open && !writeBusy && setDecisionForm(null)}>
          <DialogContent className="modal-card max-w-[440px]">
            <DialogHeader>
              <DialogTitle>{decisionForm.id ? "Edit decision" : "Add decision"}</DialogTitle>
              <DialogDescription className="sr-only">
                {decisionForm.id ? "Update this decision." : "Add a decision to the log."}
              </DialogDescription>
            </DialogHeader>
            <div style={{ display: "grid", gap: 12 }}>
              <label className="text-caption" style={{ display: "grid", gap: 6 }}>
                <span>Title</span>
                <input
                  className="search-input min-w-0 w-full"
                  value={decisionForm.title}
                  onChange={(e) => setDecisionForm((form) => form && { ...form, title: e.target.value })}
                  placeholder="Decision title"
                />
              </label>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                <div className="text-caption" style={{ display: "grid", gap: 6 }}>
                  <span>Status</span>
                  <Select
                    aria-label="Decision status"
                    className="w-full min-w-0"
                    value={decisionForm.status}
                    onValueChange={(value) => setDecisionForm((form) => form && { ...form, status: value as Decision["status"] })}
                    options={[
                      { value: "proposed", label: "Proposed" },
                      { value: "approved", label: "Approved" },
                      { value: "rejected", label: "Rejected" },
                    ]}
                  />
                </div>
                <div className="text-caption" style={{ display: "grid", gap: 6 }}>
                  <span>Impact</span>
                  <Select
                    aria-label="Decision impact"
                    className="w-full min-w-0"
                    value={decisionForm.impact}
                    onValueChange={(value) => setDecisionForm((form) => form && { ...form, impact: value as Decision["impact"] })}
                    options={[
                      { value: "critical", label: "Critical" },
                      { value: "high", label: "High" },
                      { value: "medium", label: "Medium" },
                      { value: "low", label: "Low" },
                    ]}
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                <label className="text-caption" style={{ display: "grid", gap: 6 }}>
                  <span>Owner</span>
                  <input
                    className="search-input min-w-0 w-full"
                    value={decisionForm.owner}
                    onChange={(e) => setDecisionForm((form) => form && { ...form, owner: e.target.value })}
                    placeholder="Owner"
                  />
                </label>
                <label className="text-caption" style={{ display: "grid", gap: 6 }}>
                  <span>Source</span>
                  <input
                    className="search-input min-w-0 w-full"
                    value={decisionForm.source}
                    onChange={(e) => setDecisionForm((form) => form && { ...form, source: e.target.value })}
                    placeholder="Source"
                  />
                </label>
              </div>
              <label className="text-caption" style={{ display: "grid", gap: 6 }}>
                <span>Tags</span>
                <input
                  className="search-input min-w-0 w-full"
                  value={decisionForm.tags}
                  onChange={(e) => setDecisionForm((form) => form && { ...form, tags: e.target.value })}
                  placeholder="architecture, security"
                />
              </label>
            </div>
            {writeError && <p className="error-text" role="alert">{writeError}</p>}
            <div className="modal-actions">
              <button type="button" className="btn" onClick={() => setDecisionForm(null)} disabled={writeBusy}>Cancel</button>
              <button
                className="btn btn-primary"
                onClick={saveDecision}
                disabled={decisionForm.title.trim() === "" || writeBusy}
              >
                {writeBusy ? "Saving…" : "Save decision"}
              </button>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {/* Delete confirmation */}
      {pendingDelete && (
        <Dialog open onOpenChange={(open) => !open && !writeBusy && setPendingDelete(null)}>
          <DialogContent className="modal-card max-w-[440px]">
            <DialogHeader>
              <DialogTitle>Delete this decision?</DialogTitle>
            </DialogHeader>
            <DialogDescription className="meta leading-normal">
              “{pendingDelete.title}” will be permanently removed from the decision log. This cannot
              be undone.
            </DialogDescription>
            {writeError && <p className="error-text" role="alert">{writeError}</p>}
            <div className="modal-actions">
              <button type="button" className="btn" onClick={() => setPendingDelete(null)} disabled={writeBusy}>Cancel</button>
              <button type="button" className="btn btn-danger" onClick={confirmDelete} disabled={writeBusy}>
                {writeBusy ? "Deleting…" : "Delete decision"}
              </button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
