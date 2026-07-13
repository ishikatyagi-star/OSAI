"use client";

import { useEffect, useState } from "react";
import { Bookmark, Database, Eye, EyeOff, Loader2, Play, Plus, Sparkles, Trash2 } from "lucide-react";
import {
  addSqlSource,
  deleteSqlSource,
  executeSqlQuery,
  listSqlSources,
  planSqlQuery,
  saveArtifact,
  type SqlResult,
  type SqlSourceRow,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { isDemo } from "@/lib/demo";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** Data: ask questions of live databases with a visible, editable SQL plan.
 * The LLM proposes the query; nothing runs until you approve it - and
 * execution is read-only, single-statement, row-capped. */
export default function SqlPage() {
  const [sources, setSources] = useState<SqlSourceRow[]>([]);
  const [sourceId, setSourceId] = useState<string>("");
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDsn, setNewDsn] = useState("");
  const [question, setQuestion] = useState("");
  const [sql, setSql] = useState("");
  const [plannedSourceId, setPlannedSourceId] = useState<string | null>(null);
  const [explanation, setExplanation] = useState("");
  const [result, setResult] = useState<SqlResult | null>(null);
  const [busy, setBusy] = useState<"plan" | "run" | "add" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [savingArtifact, setSavingArtifact] = useState(false);
  const [loadingSources, setLoadingSources] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [showDsn, setShowDsn] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<SqlSourceRow | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const demo = isDemo();

  function clearPlanState() {
    setSql("");
    setExplanation("");
    setResult(null);
    setSaved(false);
    setError(null);
    setPlannedSourceId(null);
  }

  async function reloadSources() {
    setLoadingSources(true);
    setLoadError("");
    if (isDemo()) {
      setSources([]);
      setLoadingSources(false);
      return;
    }
    try {
      const rows = await listSqlSources(true);
      setSources(rows);
      if (rows.length && !rows.some((r) => r.id === sourceId)) setSourceId(rows[0].id);
    } catch {
      setLoadError("Data sources could not be loaded. Check your connection and retry.");
    } finally {
      setLoadingSources(false);
    }
  }

  useEffect(() => {
    reloadSources();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleDeleteSource() {
    if (!pendingDelete || deleteBusy) return;
    const deletingId = pendingDelete.id;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await deleteSqlSource(deletingId);
      const remaining = sources.filter((source) => source.id !== deletingId);
      setSources(remaining);
      setSourceId((current) => current === deletingId ? (remaining[0]?.id ?? "") : current);
      if (sourceId === deletingId) clearPlanState();
      setPendingDelete(null);
    } catch {
      setDeleteError("The data source could not be removed. Please try again.");
    } finally {
      setDeleteBusy(false);
    }
  }

  async function handleAdd() {
    if (!newName.trim() || !newDsn.trim()) return;
    setBusy("add");
    setError(null);
    try {
      await addSqlSource({ name: newName, dsn: newDsn });
      setAdding(false);
      setNewName("");
      setNewDsn("");
      await reloadSources();
    } catch {
      setError("Could not add the source. Verify the read-only connection details and try again.");
    } finally {
      setBusy(null);
    }
  }

  async function handlePlan() {
    if (!sourceId || !question.trim() || busy) return;
    setBusy("plan");
    setError(null);
    setResult(null);
    setSaved(false);
    try {
      const p = await planSqlQuery({ source_id: sourceId, question });
      setSql(p.sql);
      setExplanation(p.explanation);
      setPlannedSourceId(sourceId);
    } catch {
      setError("Could not generate a SQL plan. Please try again.");
    } finally {
      setBusy(null);
    }
  }

  async function handleRun() {
    if (!sourceId || !sql.trim() || busy) return;
    if (plannedSourceId !== sourceId) {
      setError("This SQL plan belongs to a different data source. Generate a new plan before running it.");
      return;
    }
    setBusy("run");
    setError(null);
    setSaved(false);
    try {
      setResult(await executeSqlQuery({ source_id: sourceId, sql }));
    } catch {
      setError("The read-only query failed. Review the SQL and try again.");
    } finally {
      setBusy(null);
    }
  }

  async function handleSaveArtifact() {
    if (!result || savingArtifact || saved) return;
    setSavingArtifact(true);
    setError(null);
    try {
      await saveArtifact({
      title: question.trim() || "SQL result",
      kind: "source_table",
      data: {
        id: `sql-${Date.now()}`,
        kind: "source_table",
        title: question.trim() || "SQL result",
        subtitle: result.sql,
        rows: result.rows.slice(0, 50).map((r) => ({
          label: String(r[0] ?? ""),
          value: r.slice(1).map(String).join(" · "),
          tone: "neutral",
        })),
      },
      });
      setSaved(true);
    } catch {
      setError("The result could not be saved as an artifact. Please try again.");
    } finally {
      setSavingArtifact(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Data</h1>
          <p>
            Ask questions of live databases. Sheldon writes the SQL, shows it to you,
            and only runs what you approve - read-only, where the data lives.
          </p>
        </div>
        <Button onClick={() => setAdding((v) => !v)} disabled={demo} title={demo ? "Data connections are disabled in the shared demo" : undefined}>
          <Plus size={14} /> Add source
        </Button>
      </div>

      {adding && (
        <div className="card" style={{ marginBottom: 16, padding: 16 }}>
          <div className="flex flex-col gap-2">
            <label className="text-caption" style={{ display: "grid", gap: 6 }}>
              Source name
              <Input name="source-name" autoComplete="off" placeholder="e.g. warehouse" value={newName} onChange={(e) => setNewName(e.target.value)} />
            </label>
            <label className="text-caption" style={{ display: "grid", gap: 6 }}>
              Read-only PostgreSQL connection string
              <span className="relative flex items-center">
                <Input
                  name="dsn"
                  type={showDsn ? "text" : "password"}
                  autoComplete="off"
                  placeholder="postgresql://user:pass@host:5432/db"
                  value={newDsn}
                  onChange={(e) => setNewDsn(e.target.value)}
                  className="pr-12"
                />
                <Button type="button" size="icon" variant="ghost" className="absolute right-1" onClick={() => setShowDsn((visible) => !visible)} aria-label={showDsn ? "Hide connection string" : "Show connection string"}>
                  {showDsn ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </Button>
              </span>
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setAdding(false)} disabled={busy === "add"}>
                Cancel
              </Button>
              <Button onClick={handleAdd} disabled={busy === "add" || !newName.trim() || !newDsn.trim()}>
                {busy === "add" ? <Loader2 className="size-4 animate-spin" /> : "Connect"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {loadError ? (
        <div className="card async-state" role="alert">
          <div>
            <p className="error-text" style={{ marginBottom: 12 }}>{loadError}</p>
            <button type="button" className="btn btn-primary" onClick={reloadSources}>Retry</button>
          </div>
        </div>
      ) : loadingSources ? (
        <div className="card async-state" role="status" aria-live="polite">Loading data sources…</div>
      ) : sources.length === 0 ? (
        <div className="card" style={{ padding: 24, textAlign: "center" }}>
          <Database className="mx-auto mb-2 size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
             {demo ? "Live database connections are disabled in the shared demo workspace." : "No data sources yet. Connect a PostgreSQL database to ask it questions."}
          </p>
        </div>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <label className="text-xs text-muted-foreground">Source</label>
            <select
              aria-label="Data source"
              value={sourceId}
              onChange={(e) => {
                setSourceId(e.target.value);
                clearPlanState();
              }}
              style={{
                background: "var(--bg-surface)",
                color: "inherit",
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: "6px 10px",
                fontSize: 13,
              }}
            >
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            {sourceId && (
              <Button
                size="sm"
                variant="ghost"
                className="text-destructive"
                aria-label={`Remove source: ${sources.find((source) => source.id === sourceId)?.name ?? "selected source"}`}
                onClick={() => { setDeleteError(""); setPendingDelete(sources.find((source) => source.id === sourceId) ?? null); }}
              >
                <Trash2 className="size-3.5" />
              </Button>
            )}
          </div>

          <div className="card" style={{ padding: 16, marginBottom: 16 }}>
            <div className="flex gap-2">
              <Input
                placeholder="e.g. How many documents were ingested per connector last week?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handlePlan()}
              />
              <Button onClick={handlePlan} disabled={busy !== null || !question.trim()}>
                {busy === "plan" ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
                Plan
              </Button>
            </div>

            {sql && (
              <div className="mt-3 flex flex-col gap-2">
                {explanation && <p className="text-xs text-muted-foreground">{explanation}</p>}
                <Textarea
                  rows={4}
                  aria-label="Generated SQL (editable)"
                  value={sql}
                  onChange={(e) => setSql(e.target.value)}
                  style={{ fontFamily: "monospace", fontSize: 12 }}
                />
                <div className="flex justify-end">
                  <Button onClick={handleRun} disabled={busy !== null || !sql.trim() || plannedSourceId !== sourceId}>
                    {busy === "run" ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
                    Run query
                  </Button>
                </div>
              </div>
            )}

            {error && <p className="mt-2 text-xs text-red-500" role="alert">{error}</p>}
          </div>

          {result && (
            <div className="card" style={{ padding: 16 }}>
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  {result.row_count} row{result.row_count === 1 ? "" : "s"}
                </span>
                <Button size="sm" variant="ghost" onClick={handleSaveArtifact} disabled={saved || savingArtifact}>
                  {savingArtifact ? <Loader2 className="size-3.5 animate-spin" /> : <Bookmark className="size-3.5" />}
                  {savingArtifact ? "Saving..." : saved ? "Saved" : "Save as artifact"}
                </Button>
              </div>
              <div className="table-scroll" tabIndex={0} role="region" aria-label="SQL query results">
                <table className="data-table">
                  <thead>
                    <tr>
                      {result.columns.map((c) => (
                        <th key={c} className="border-b border-[var(--border)] px-2 py-1.5 text-xs font-semibold">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((r, i) => (
                      <tr key={i}>
                        {r.map((v, j) => (
                          <td key={j} className="border-b border-[var(--border)] px-2 py-1.5">
                            {String(v ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {pendingDelete && (
        <Dialog open onOpenChange={(open) => !open && !deleteBusy && setPendingDelete(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Remove this data source?</DialogTitle>
              <DialogDescription>“{pendingDelete.name}” will be removed from Sheldon. The database itself will not be changed.</DialogDescription>
            </DialogHeader>
            {deleteError && <p className="error-text" role="alert">{deleteError}</p>}
            <DialogFooter>
              <button type="button" className="btn" onClick={() => setPendingDelete(null)} disabled={deleteBusy}>Cancel</button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={handleDeleteSource}
                disabled={deleteBusy}
              >
                {deleteBusy ? "Removing..." : "Remove source"}
              </button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
