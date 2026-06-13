"use client";

import { useMemo, useState } from "react";
import { DEMO_DECISIONS, type Decision } from "@/lib/demo-data";

const IMPACT_META: Record<Decision["impact"], { cls: string }> = {
  critical: { cls: "badge-red" },
  high:     { cls: "badge-orange" },
  medium:   { cls: "badge-yellow" },
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

export default function DecisionsPage() {
  const [decisions, setDecisions] = useState<Decision[]>(DEMO_DECISIONS);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | Decision["status"]>("all");
  const [impactFilter, setImpactFilter] = useState<"all" | Decision["impact"]>("all");
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [pendingDelete, setPendingDelete] = useState<Decision | null>(null);

  // Add / edit editor. `editing` holds the working draft; `isNew` decides
  // whether saving inserts or updates. Tags are edited as a raw comma string.
  const [editing, setEditing] = useState<Decision | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [tagsInput, setTagsInput] = useState("");

  function blankDecision(): Decision {
    return {
      id: `dec-${Date.now()}`,
      title: "",
      tags: [],
      status: "proposed",
      impact: "medium",
      owner: "",
      date: new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }),
    };
  }

  function openAdd() {
    setEditing(blankDecision());
    setIsNew(true);
    setTagsInput("");
  }

  function openEdit(d: Decision) {
    setEditing({ ...d });
    setIsNew(false);
    setTagsInput(d.tags.join(", "));
  }

  function patchDraft(patch: Partial<Decision>) {
    setEditing((e) => (e ? { ...e, ...patch } : e));
  }

  function saveDecision() {
    if (!editing) return;
    const title = editing.title.trim();
    if (!title) return;
    const record: Decision = {
      ...editing,
      title,
      owner: editing.owner.trim() || "Unassigned",
      tags: tagsInput.split(",").map((t) => t.trim()).filter(Boolean),
    };
    setDecisions((prev) =>
      prev.some((d) => d.id === record.id)
        ? prev.map((d) => (d.id === record.id ? record : d))
        : [record, ...prev]
    );
    setEditing(null);
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  function confirmDelete() {
    if (!pendingDelete) return;
    setDecisions((prev) => prev.filter((d) => d.id !== pendingDelete.id));
    setPendingDelete(null);
  }

  const filtered = useMemo(() => {
    const result = decisions.filter((d) => {
      const matchesSearch =
        search === "" ||
        d.title.toLowerCase().includes(search.toLowerCase()) ||
        d.tags.some((t) => t.includes(search.toLowerCase()));
      const matchesStatus = statusFilter === "all" || d.status === statusFilter;
      const matchesImpact = impactFilter === "all" || d.impact === impactFilter;
      return matchesSearch && matchesStatus && matchesImpact;
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
  }, [decisions, search, statusFilter, impactFilter, sortKey, sortDir]);

  function SortableTh({ label, k, width }: { label: string; k: SortKey; width?: number }) {
    const active = sortKey === k;
    return (
      <th
        className="sortable"
        style={width ? { width } : undefined}
        onClick={() => toggleSort(k)}
        aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
      >
        {label}
        <span className={`sort-caret${active ? "" : " inactive"}`}>
          {active ? (sortDir === "asc" ? "↑" : "↓") : "↕"}
        </span>
      </th>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Decision Log</h1>
          <p>Track all key decisions made across your org — owned, dated, and tagged.</p>
        </div>
        <button className="btn btn-primary" onClick={openAdd}>+ Add Decision</button>
      </div>

      {/* Search + filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
        <input
          className="search-input"
          style={{ maxWidth: 280 }}
          placeholder="Search decisions…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
        >
          <option value="all">All statuses</option>
          <option value="proposed">Proposed</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
        <select
          className="select"
          value={impactFilter}
          onChange={(e) => setImpactFilter(e.target.value as typeof impactFilter)}
        >
          <option value="all">All impact levels</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <span className="meta" style={{ alignSelf: "center", marginLeft: "auto" }}>
          {filtered.length} of {decisions.length} decisions
        </span>
      </div>

      {/* Table */}
      <table className="data-table">
        <thead>
          <tr>
            <SortableTh label="Decision" k="title" />
            <SortableTh label="Status" k="status" />
            <SortableTh label="Impact" k="impact" />
            <SortableTh label="Owner" k="owner" />
            <SortableTh label="Date" k="date" />
            <th style={{ width: 80 }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((d) => (
            <tr key={d.id}>
              <td>
                <div style={{ fontWeight: 600, marginBottom: 5, fontSize: 13, color: "var(--text-primary)" }}>
                  {d.title}
                </div>
                <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
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
                <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{d.owner}</span>
              </td>
              <td>
                <span className="mono">{d.date}</span>
              </td>
              <td>
                <div style={{ display: "flex", gap: 6 }}>
                  <button
                    className="btn-ghost btn"
                    style={{ fontSize: 11, padding: "3px 7px" }}
                    onClick={() => openEdit(d)}
                  >
                    Edit
                  </button>
                  <button
                    className="btn-ghost btn btn-danger"
                    style={{ fontSize: 11, padding: "3px 7px" }}
                    onClick={() => setPendingDelete(d)}
                    aria-label={`Delete decision: ${d.title}`}
                  >
                    ✕
                  </button>
                </div>
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={6} style={{ textAlign: "center", color: "var(--text-muted)", padding: "32px 0" }}>
                No decisions match this filter.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {/* Delete confirmation */}
      {pendingDelete && (
        <div className="modal-overlay" onClick={() => setPendingDelete(null)} role="dialog" aria-modal="true">
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h2>Delete this decision?</h2>
            <p className="meta" style={{ lineHeight: 1.5 }}>
              “{pendingDelete.title}” will be permanently removed from the decision log. This cannot
              be undone.
            </p>
            <div className="modal-actions">
              <button className="btn" onClick={() => setPendingDelete(null)}>Cancel</button>
              <button className="btn btn-danger" onClick={confirmDelete}>Delete decision</button>
            </div>
          </div>
        </div>
      )}

      {/* Add / edit editor */}
      {editing && (
        <div className="modal-overlay" onClick={() => setEditing(null)} role="dialog" aria-modal="true">
          <div className="modal-card" style={{ maxWidth: 520 }} onClick={(e) => e.stopPropagation()}>
            <h2>{isNew ? "Add decision" : "Edit decision"}</h2>

            <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 16 }}>
              <div className="form-group">
                <label>Decision</label>
                <input
                  className="auth-input"
                  autoFocus
                  placeholder="What was decided?"
                  value={editing.title}
                  onChange={(e) => patchDraft({ title: e.target.value })}
                />
              </div>

              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                <div className="form-group" style={{ flex: 1, minWidth: 140 }}>
                  <label>Status</label>
                  <select
                    className="select"
                    value={editing.status}
                    onChange={(e) => patchDraft({ status: e.target.value as Decision["status"] })}
                  >
                    <option value="proposed">Proposed</option>
                    <option value="approved">Approved</option>
                    <option value="rejected">Rejected</option>
                  </select>
                </div>
                <div className="form-group" style={{ flex: 1, minWidth: 140 }}>
                  <label>Impact</label>
                  <select
                    className="select"
                    value={editing.impact}
                    onChange={(e) => patchDraft({ impact: e.target.value as Decision["impact"] })}
                  >
                    <option value="critical">Critical</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
              </div>

              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                <div className="form-group" style={{ flex: 1, minWidth: 140 }}>
                  <label>Owner</label>
                  <input
                    className="auth-input"
                    placeholder="e.g. Ishika T."
                    value={editing.owner}
                    onChange={(e) => patchDraft({ owner: e.target.value })}
                  />
                </div>
                <div className="form-group" style={{ flex: 1, minWidth: 140 }}>
                  <label>Date</label>
                  <input
                    className="auth-input"
                    placeholder="Jun 13, 2026"
                    value={editing.date}
                    onChange={(e) => patchDraft({ date: e.target.value })}
                  />
                </div>
              </div>

              <div className="form-group">
                <label>Tags</label>
                <input
                  className="auth-input"
                  placeholder="comma separated, e.g. architecture, data"
                  value={tagsInput}
                  onChange={(e) => setTagsInput(e.target.value)}
                />
              </div>
            </div>

            <div className="modal-actions">
              <button className="btn" onClick={() => setEditing(null)}>Cancel</button>
              <button
                className="btn btn-primary"
                onClick={saveDecision}
                disabled={!editing.title.trim()}
              >
                {isNew ? "Add decision" : "Save changes"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
