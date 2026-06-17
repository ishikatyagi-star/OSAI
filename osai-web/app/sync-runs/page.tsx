"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSyncRuns } from "@/lib/api";
import { DEMO_SYNC_RUNS, DEMO_STATS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
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
      if (data.length) setRuns(data);
      else if (isDemo()) setRuns(DEMO_SYNC_RUNS);
    });
  }, []);

  const demo = isDemo();
  const display = runs.length ? runs : demo ? DEMO_SYNC_RUNS : [];

  const totalDocs = display.reduce((sum, r) => sum + (r.documents_indexed ?? 0), 0);
  const succeeded = display.filter((r) => r.status === "succeeded").length;
  const failed = display.filter((r) => r.status === "failed").length;

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Sync Runs</h1>
          <p>
            Ingestion activity across all connected sources. Each run fetches, chunks, and indexes
            documents into the OSAI knowledge base.
          </p>
        </div>
      </div>

      {/* Summary stats — dashboard stat-card styling; color reserved for status */}
      <div className="stats-grid stats-grid--auto">
        {[
          { label: "Total runs", value: display.length, color: "var(--text-primary)" },
          { label: "Succeeded", value: succeeded, color: "var(--green)" },
          { label: "Failed", value: failed, color: failed > 0 ? "var(--red)" : "var(--text-primary)" },
          { label: "Docs indexed (session)", value: totalDocs.toLocaleString(), color: "var(--text-primary)" },
          { label: "Total in knowledge base", value: (demo ? DEMO_STATS.documentsIndexed : totalDocs).toLocaleString(), color: "var(--text-primary)" },
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
            return (
              <div key={key} className="connector-pill">
                <span>{meta.icon}</span>
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
                  <span className="text-base">{meta.icon}</span>
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
                    <span className="meta">📥 {run.documents_seen} seen</span>
                  </div>
                  <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <span className="meta" style={{ color: run.documents_indexed > 0 ? "var(--green)" : undefined }}>
                      ✓ {run.documents_indexed} indexed
                    </span>
                  </div>
                  {run.status === "succeeded" && run.documents_seen - run.documents_indexed > 0 && (
                    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                      <span
                        className="meta"
                        title="Skipped during indexing — usually empty, too short, or an unsupported format."
                        style={{ cursor: "help" }}
                      >
                        ⓘ {run.documents_seen - run.documents_indexed} skipped
                      </span>
                    </div>
                  )}
                  {run.documents_indexed > 0 && run.documents_seen > 0 && (
                    <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, minWidth: 120 }}>
                      <div style={{ flex: 1, height: 3, background: "rgba(255,255,255,0.08)", borderRadius: 9999 }}>
                        <div
                          style={{
                            width: `${(run.documents_indexed / run.documents_seen) * 100}%`,
                            height: "100%",
                            background: "var(--green)",
                            borderRadius: 9999,
                          }}
                        />
                      </div>
                      <span className="text-[10px] font-semibold" style={{ color: "var(--green)" }}>
                        {Math.round((run.documents_indexed / run.documents_seen) * 100)}%
                      </span>
                    </div>
                  )}
                </div>

                {run.error && (
                  <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                    <span className="error-text">⚠ {run.error}</span>
                    <Link
                      href="/integrations"
                      className="text-micro font-semibold"
                      style={{ color: "var(--accent)", whiteSpace: "nowrap" }}
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
