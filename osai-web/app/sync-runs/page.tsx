"use client";

import { useEffect, useState } from "react";
import { getSyncRuns } from "@/lib/api";
import { DEMO_SYNC_RUNS, DEMO_STATS } from "@/lib/demo-data";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { SyncRun } from "@/lib/types";

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const STATUS_BADGE: Record<string, string> = {
  succeeded: "badge-green",
  failed: "badge-red",
  running: "badge-yellow",
  pending: "badge-grey",
};

export default function SyncRunsPage() {
  const [runs, setRuns] = useState<SyncRun[]>([]);

  useEffect(() => {
    getSyncRuns().then((data) => {
      const hasReal = data.some((r) => r.documents_indexed > 0);
      setRuns(hasReal ? data : DEMO_SYNC_RUNS);
    });
  }, []);

  const display = runs.length ? runs : DEMO_SYNC_RUNS;

  const totalDocs = display.reduce((sum, r) => sum + (r.documents_indexed ?? 0), 0);
  const succeeded = display.filter((r) => r.status === "succeeded").length;
  const failed = display.filter((r) => r.status === "failed").length;

  return (
    <div>
      <h1>Sync Runs</h1>
      <p className="page-subtitle">
        Ingestion activity across all connected sources. Each run fetches, chunks, and indexes
        documents into the OSAI knowledge base.
      </p>

      {/* Summary stats */}
      <div style={{ display: "flex", gap: 16, marginBottom: 32, flexWrap: "wrap" }}>
        {[
          { label: "Total runs", value: display.length, color: undefined },
          { label: "Succeeded", value: succeeded, color: "#22c55e" },
          { label: "Failed", value: failed, color: failed > 0 ? "#ff5577" : undefined },
          { label: "Docs indexed (session)", value: totalDocs.toLocaleString(), color: "#0099ff" },
          { label: "Total in knowledge base", value: DEMO_STATS.documentsIndexed.toLocaleString(), color: "#b3a0ff" },
        ].map((s) => (
          <div key={s.label} className="mini-stat">
            <span className="mini-stat-value" style={{ color: s.color }}>{s.value}</span>
            <span className="mini-stat-label">{s.label}</span>
          </div>
        ))}
      </div>

      {/* Per-connector summary */}
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ marginBottom: 12 }}>Source Breakdown</h2>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {Object.entries(DEMO_STATS.docsPerConnector).map(([key, count]) => {
            const meta = CONNECTOR_META[key];
            if (!meta) return null;
            return (
              <div
                key={key}
                className="connector-pill"
                style={{ borderColor: `${meta.color}25`, background: `${meta.color}08` }}
              >
                <span style={{ color: meta.color }}>{meta.icon}</span>
                <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{meta.label}</span>
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
        <p className="empty-state">No sync runs yet. Trigger a sync from Integrations.</p>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        {display.map((run, i) => {
          const meta = CONNECTOR_META[run.connector_key] ?? {
            label: run.connector_key,
            icon: "⚙",
            color: "var(--text-secondary)",
          };
          const isLast = i === display.length - 1;

          return (
            <div
              key={run.id}
              style={{ display: "flex", gap: 0, alignItems: "stretch" }}
            >
              {/* Timeline rail */}
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 36, flexShrink: 0 }}>
                <div
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: "50%",
                    background: run.status === "succeeded" ? "#22c55e" : run.status === "failed" ? "#ff5577" : "var(--text-secondary)",
                    border: "2px solid rgba(255,255,255,0.1)",
                    marginTop: 18,
                    flexShrink: 0,
                    boxShadow: run.status === "succeeded" ? "0 0 6px #22c55e60" : "none",
                  }}
                />
                {!isLast && (
                  <div style={{ flex: 1, width: 1, background: "rgba(255,255,255,0.06)", marginTop: 4 }} />
                )}
              </div>

              {/* Card */}
              <div
                className="card"
                style={{
                  flex: 1,
                  marginLeft: 12,
                  marginBottom: isLast ? 0 : 12,
                  padding: "14px 18px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                  <span style={{ fontSize: 16, color: meta.color }}>{meta.icon}</span>
                  <span style={{ fontWeight: 600, fontSize: 13, color: "var(--text-primary)" }}>{meta.label}</span>
                  <span className={`badge ${STATUS_BADGE[run.status] ?? "badge-grey"}`}>
                    {run.status}
                  </span>
                  <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-muted)" }}>
                    {timeAgo(run.started_at)}
                  </span>
                </div>

                <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
                  <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <span className="meta">📥 {run.documents_seen} seen</span>
                  </div>
                  <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <span className="meta" style={{ color: run.documents_indexed > 0 ? "#22c55e" : undefined }}>
                      ✓ {run.documents_indexed} indexed
                    </span>
                  </div>
                  {run.documents_indexed > 0 && run.documents_seen > 0 && (
                    <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, minWidth: 120 }}>
                      <div style={{ flex: 1, height: 3, background: "rgba(255,255,255,0.08)", borderRadius: 9999 }}>
                        <div
                          style={{
                            width: `${(run.documents_indexed / run.documents_seen) * 100}%`,
                            height: "100%",
                            background: "#22c55e",
                            borderRadius: 9999,
                          }}
                        />
                      </div>
                      <span style={{ fontSize: 10, color: "#22c55e", fontWeight: 600 }}>
                        {Math.round((run.documents_indexed / run.documents_seen) * 100)}%
                      </span>
                    </div>
                  )}
                </div>

                {run.error && (
                  <p className="error-text" style={{ marginTop: 8, fontSize: 12 }}>⚠ {run.error}</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
