"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Check, Download, Info, RotateCw } from "lucide-react";
import { getDashboardMetrics, getSyncRunPage, type SyncRunPage } from "@/lib/api";
import { DEMO_SYNC_RUNS, DEMO_STATS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { CONNECTOR_META, getConnectorIcon } from "@/lib/connector-meta";
import type { SyncRun } from "@/lib/types";
import { brandText, timeAgo } from "@/lib/utils";
import { SheldonMascot } from "@/components/sheldon-mascot";


const STATUS_BADGE: Record<string, string> = {
  succeeded: "badge-green",
  failed: "badge-red",
  running: "badge-yellow",
  pending: "badge-grey",
};

export default function SyncRunsPage() {
  const [runs, setRuns] = useState<SyncRun[]>([]);
  // Active searchable index size - the single source of truth shared with the
  // dashboard/analytics/integration cards. NOT the sum of historical runs (which
  // double-counts re-syncs and old, since-removed accounts).
  const [activeDocs, setActiveDocs] = useState<number | null>(null);
  const [summary, setSummary] = useState<SyncRunPage["summary"] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [loadMoreError, setLoadMoreError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    setLoadMoreError("");
    if (isDemo()) {
      setRuns(DEMO_SYNC_RUNS);
      setSummary(null);
      setNextCursor(null);
      setActiveDocs(DEMO_STATS.documentsIndexed);
      setLoading(false);
      return;
    }
    try {
      const [runsResult, metricsResult] = await Promise.allSettled([
        getSyncRunPage(25, undefined, true),
        getDashboardMetrics(true),
      ]);
      if (runsResult.status === "rejected") throw runsResult.reason;
      setRuns(runsResult.value.items);
      setSummary(runsResult.value.summary);
      setNextCursor(runsResult.value.next_cursor);
      setActiveDocs(metricsResult.status === "fulfilled" ? metricsResult.value.total_documents : null);
    } catch {
      setLoadError("Sync activity could not be loaded. Check your connection and retry.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setLoadMoreError("");
    try {
      const page = await getSyncRunPage(25, nextCursor, true);
      setRuns((current) => [...current, ...page.items]);
      setSummary(page.summary);
      setNextCursor(page.next_cursor);
    } catch {
      setLoadMoreError("More sync runs could not be loaded. Retry when your connection is stable.");
    } finally {
      setLoadingMore(false);
    }
  }

  const demo = isDemo();
  const display = (runs.length ? runs : demo ? DEMO_SYNC_RUNS : [])
    .slice()
    .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));

  const totalRuns = demo ? display.length : summary?.total_runs ?? 0;
  const totalDocs = demo
    ? display.reduce((sum, r) => sum + (r.documents_indexed ?? 0), 0)
    : summary?.documents_indexed ?? 0;
  const knowledgeBaseDocs = demo ? DEMO_STATS.documentsIndexed : activeDocs;
  const succeeded = demo
    ? display.filter((r) => r.status === "succeeded").length
    : summary?.status_counts.succeeded ?? 0;
  const failed = demo
    ? display.filter((r) => r.status === "failed").length
    : summary?.status_counts.failed ?? 0;
  const sourceRows = demo
    ? Object.entries(DEMO_STATS.docsPerConnector).map(([key, documents]) => ({
        key,
        runs: display.filter((run) => run.connector_key === key).length,
        documents,
      }))
    : Object.entries(summary?.by_connector ?? {}).map(([key, aggregate]) => ({
        key,
        runs: aggregate.total_runs,
        documents: aggregate.documents_indexed,
      }));

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Sync Runs</h1>
          <p>
            Ingestion activity across all connected sources. Each run fetches, chunks, and indexes
            documents into the Sheldon knowledge base.
          </p>
        </div>
        <button type="button" className="btn" onClick={load} disabled={loading} aria-busy={loading}>
          <RotateCw className={`size-3.5${loading ? " animate-spin" : ""}`} aria-hidden="true" /> Refresh
        </button>
      </div>

      {loadError ? (
        <div className="card async-state" role="alert">
          <div>
            <p className="error-text" style={{ marginBottom: 12 }}>{loadError}</p>
            <button type="button" className="btn btn-primary" onClick={load}>Retry</button>
          </div>
        </div>
      ) : loading ? (
        <div className="card async-state" role="status" aria-live="polite">Loading sync activity…</div>
      ) : (
        <>

      {/* Summary stats - dashboard stat-card styling; color reserved for status */}
      <div className="stats-grid stats-grid--auto">
        {[
          { label: "Total runs (all time)", value: totalRuns, color: "var(--text-primary)" },
          { label: "Succeeded (all time)", value: succeeded, color: "var(--green)" },
          { label: "Failed (all time)", value: failed, color: failed > 0 ? "var(--red)" : "var(--text-primary)" },
          { label: "Docs indexed (all runs)", value: totalDocs.toLocaleString(), color: "var(--text-primary)" },
          { label: "Active in knowledge base", value: knowledgeBaseDocs === null ? "Unavailable" : knowledgeBaseDocs.toLocaleString(), color: "var(--text-primary)" },
        ].map((s) => (
          <div key={s.label} className="stat-card">
            <div className="stat-card-label">{s.label}</div>
            <div className="stat-card-value" style={{ color: s.color }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Per-connector summary */}
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ marginBottom: 12 }}>Source Breakdown</h2>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {sourceRows.map(({ key, runs: sourceRuns, documents }) => {
            const meta = CONNECTOR_META[key];
            const Icon = getConnectorIcon(key);
            return (
              <div key={key} className="connector-pill">
                <Icon size={14} strokeWidth={1.8} />
                <span className="font-semibold" style={{ color: "var(--text-primary)" }}>{meta?.label ?? key}</span>
                <span className="badge badge-grey" style={{ fontSize: 10 }}>
                  {sourceRuns.toLocaleString()} run{sourceRuns === 1 ? "" : "s"} · {documents.toLocaleString()} indexed
                </span>
              </div>
            );
          })}
          {sourceRows.length === 0 && <p className="meta">No source activity yet.</p>}
        </div>
      </div>

      {/* Timeline */}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <h2>Activity Timeline</h2>
        <span className="meta">Showing {display.length.toLocaleString()} of {totalRuns.toLocaleString()} runs</span>
      </div>
      {display.length === 0 && (
        <div className="empty-state mascot-empty-state">
          <SheldonMascot state="syncing" size={88} />
          <p>No sync runs yet. Trigger a sync from Integrations.</p>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        {display.map((run, i) => {
          const meta = CONNECTOR_META[run.connector_key] ?? {
            label: run.connector_key,
            color: "var(--text-secondary)",
          };
          const Icon = getConnectorIcon(run.connector_key);
          const isLast = i === display.length - 1;

          const dotClass =
            run.status === "succeeded"
              ? "timeline-dot timeline-dot--success"
              : run.status === "failed"
                ? "timeline-dot timeline-dot--failed"
                : "timeline-dot timeline-dot--default";

          return (
            <div
              key={run.id}
              style={{ display: "flex", gap: 0, alignItems: "stretch" }}
            >
              {/* Timeline rail */}
              <div className="timeline-rail">
                <div className={dotClass} />
                {!isLast && <div className="timeline-line" />}
              </div>

              {/* Card */}
              <div
                className="card timeline-card"
                style={{ marginBottom: isLast ? 0 : undefined }}
              >
                <div className="sync-run-header">
                  <span className="connector-inline-icon" aria-hidden>
                    <Icon size={15} strokeWidth={1.8} />
                  </span>
                  <span className="text-caption" style={{ color: "var(--text-primary)", fontWeight: 600 }}>{meta.label}</span>
                  <span className={`badge ${STATUS_BADGE[run.status] ?? "badge-grey"}`}>
                    {run.status}
                  </span>
                  <span className="meta" style={{ marginLeft: "auto" }}>
                    {timeAgo(run.started_at)}
                  </span>
                </div>

                <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
                  <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <span className="meta" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                      <Download size={12} strokeWidth={1.8} /> {run.documents_seen} seen
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <span className="meta" style={{ color: run.documents_indexed > 0 ? "var(--green)" : undefined, display: "inline-flex", alignItems: "center", gap: 4 }}>
                      <Check size={12} strokeWidth={2} /> {run.documents_indexed} indexed
                    </span>
                  </div>
                  {run.status === "succeeded" && run.documents_seen - run.documents_indexed > 0 && (
                    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                      <span
                        className="meta"
                        title="Skipped during indexing - usually empty, too short, or an unsupported format."
                        tabIndex={0}
                        aria-label={`${run.documents_seen - run.documents_indexed} documents skipped during indexing; usually empty, too short, or unsupported.`}
                        style={{ cursor: "help", display: "inline-flex", alignItems: "center", gap: 4 }}
                      >
                        <Info size={12} strokeWidth={1.8} /> {run.documents_seen - run.documents_indexed} skipped
                      </span>
                    </div>
                  )}
                  {run.documents_indexed > 0 && run.documents_seen > 0 && (
                    <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, minWidth: 120 }}>
                      <div
                        style={{ flex: 1, height: 3, background: "var(--bg-hover)", borderRadius: 9999 }}
                        role="progressbar"
                        aria-label={`${meta.label} documents indexed`}
                        aria-valuemin={0}
                        aria-valuemax={run.documents_seen}
                        aria-valuenow={run.documents_indexed}
                      >
                        <div
                          style={{
                            width: `${(run.documents_indexed / run.documents_seen) * 100}%`,
                            height: "100%",
                            background: "var(--green)",
                            borderRadius: 9999,
                          }}
                        />
                      </div>
                      <span className="text-xs font-semibold" style={{ color: "var(--green)" }}>
                        {Math.round((run.documents_indexed / run.documents_seen) * 100)}%
                      </span>
                    </div>
                  )}
                </div>

                {run.error && (
                  <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                    <span className="error-text inline-flex items-center gap-1.5">
                      <AlertTriangle size={13} strokeWidth={1.8} />
                      {brandText(run.error)}
                    </span>
                    <Link
                      href="/integrations"
                      className="text-micro font-semibold sync-run-fix-link"
                      style={{ color: "var(--text-primary)", whiteSpace: "nowrap" }}
                    >
                      Fix in Integrations →
                    </Link>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {loadMoreError && <p className="error-text" role="alert" style={{ marginTop: 16 }}>{loadMoreError}</p>}
      {nextCursor && (
        <div style={{ display: "flex", justifyContent: "center", marginTop: 20 }}>
          <button type="button" className="btn" onClick={loadMore} disabled={loadingMore} aria-busy={loadingMore}>
            <RotateCw className={`size-3.5${loadingMore ? " animate-spin" : ""}`} aria-hidden="true" />
            {loadingMore ? "Loading…" : loadMoreError ? "Retry loading more" : "Load more"}
          </button>
        </div>
      )}
        </>
      )}
    </div>
  );
}
