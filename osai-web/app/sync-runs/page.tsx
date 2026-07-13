"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Check, Download, Info } from "lucide-react";
import { getSyncRuns, getDashboardMetrics } from "@/lib/api";
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
  const [activeDocs, setActiveDocs] = useState(0);

  useEffect(() => {
    getSyncRuns().then((data) => {
      if (data.length) setRuns(data);
      else if (isDemo()) setRuns(DEMO_SYNC_RUNS);
    });
    if (!isDemo()) getDashboardMetrics().then((m) => setActiveDocs(m.total_documents));
  }, []);

  const demo = isDemo();
  const display = runs.length ? runs : demo ? DEMO_SYNC_RUNS : [];

  const totalDocs = display.reduce((sum, r) => sum + (r.documents_indexed ?? 0), 0);
  const knowledgeBaseDocs = demo ? DEMO_STATS.documentsIndexed : activeDocs;
  const succeeded = display.filter((r) => r.status === "succeeded").length;
  const failed = display.filter((r) => r.status === "failed").length;

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
      </div>

      {/* Summary stats - dashboard stat-card styling; color reserved for status */}
      <div className="stats-grid stats-grid--auto">
        {[
          { label: "Total runs", value: display.length, color: "var(--text-primary)" },
          { label: "Succeeded", value: succeeded, color: "var(--green)" },
          { label: "Failed", value: failed, color: failed > 0 ? "var(--red)" : "var(--text-primary)" },
          { label: "Docs indexed (all runs)", value: totalDocs.toLocaleString(), color: "var(--text-primary)" },
          { label: "Active in knowledge base", value: knowledgeBaseDocs.toLocaleString(), color: "var(--text-primary)" },
        ].map((s) => (
          <div key={s.label} className="stat-card">
            <div className="stat-card-label">{s.label}</div>
            <div className="stat-card-value" style={{ color: s.color }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Per-connector summary */}
      <div style={{ marginBottom: 28, display: demo ? "block" : "none" }}>
        <h2 style={{ marginBottom: 12 }}>Source Breakdown</h2>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {Object.entries(DEMO_STATS.docsPerConnector).map(([key, count]) => {
            const meta = CONNECTOR_META[key];
            if (!meta) return null;
            const Icon = meta.icon;
            return (
              <div key={key} className="connector-pill">
                <Icon size={14} strokeWidth={1.8} />
                <span className="font-semibold" style={{ color: "var(--text-primary)" }}>{meta.label}</span>
                <span className="badge badge-grey" style={{ fontSize: 10 }}>
                  {count.toLocaleString()} docs
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Timeline */}
      <h2 style={{ marginBottom: 16 }}>Activity Timeline</h2>
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
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
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
                        style={{ cursor: "help", display: "inline-flex", alignItems: "center", gap: 4 }}
                      >
                        <Info size={12} strokeWidth={1.8} /> {run.documents_seen - run.documents_indexed} skipped
                      </span>
                    </div>
                  )}
                  {run.documents_indexed > 0 && run.documents_seen > 0 && (
                    <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, minWidth: 120 }}>
                      <div style={{ flex: 1, height: 3, background: "var(--bg-hover)", borderRadius: 9999 }}>
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
    </div>
  );
}
