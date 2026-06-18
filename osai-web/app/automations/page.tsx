"use client";

import { useEffect, useState } from "react";
import { Play, Trash2, Plus, Loader2 } from "lucide-react";
import {
  createAutomation,
  deleteAutomation,
  getAutomations,
  runAutomation,
  type Automation,
} from "@/lib/api";

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

export default function AutomationsPage() {
  const [items, setItems] = useState<Automation[]>([]);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [cadence, setCadence] = useState<string>("daily");
  const [creating, setCreating] = useState(false);
  const [running, setRunning] = useState<string | null>(null);
  const [result, setResult] = useState<{ id: string; text: string } | null>(null);

  function refresh() {
    getAutomations().then(setItems);
  }
  useEffect(refresh, []);

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

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Automations</h1>
          <p>
            Describe a task in plain English and OSAI runs it for you — on demand now, or on a
            cadence once scheduling is enabled. e.g. &quot;Summarise this week&apos;s open Freshdesk
            escalations.&quot;
          </p>
        </div>
      </div>

      {/* Create form */}
      <form className="card" onSubmit={handleCreate} style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
          <input
            className="search-input"
            placeholder="Automation name (e.g. Weekly support digest)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ flex: 1, minWidth: 240 }}
          />
          <select className="select" value={cadence} onChange={(e) => setCadence(e.target.value)}>
            {CADENCES.map((c) => (
              <option key={c} value={c}>{c === "manual" ? "On demand" : c}</option>
            ))}
          </select>
        </div>
        <textarea
          className="search-input"
          placeholder="What should OSAI do? e.g. Summarise open blockers across Notion and Slack and list owners."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          style={{ width: "100%", resize: "vertical", marginBottom: 10 }}
        />
        <button type="submit" className="btn btn-primary" disabled={creating}>
          {creating ? <Loader2 className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
          Create automation
        </button>
      </form>

      {/* List */}
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
    </div>
  );
}
