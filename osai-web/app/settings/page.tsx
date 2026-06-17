"use client";

import { useState } from "react";
import Link from "next/link";
import { FlaskConical, Route, ChevronRight, Trash2, type LucideIcon } from "lucide-react";
import { resetWorkspaceContent } from "@/lib/api";

type SettingsLink = {
  href: string;
  icon: LucideIcon;
  title: string;
  description: string;
};

const LINKS: SettingsLink[] = [
  {
    href: "/integrations?tab=routing",
    icon: Route,
    title: "Data Routing",
    description:
      "Classify information into Normal / Amber / Red tiers and control which connectors and LLMs each tier may use. Now lives with Integrations.",
  },
  {
    href: "/settings/advanced",
    icon: FlaskConical,
    title: "Advanced · Evals",
    description:
      "Quality and regression tracking for OSAI's answers and routing. Moved out of the main nav to keep things simple.",
  },
];

export default function SettingsPage() {
  const [confirming, setConfirming] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetMsg, setResetMsg] = useState("");

  async function handleReset() {
    const orgId = localStorage.getItem("osai_org_id");
    if (!orgId) return;
    setResetting(true);
    setResetMsg("");
    try {
      const res = await resetWorkspaceContent(orgId);
      const total = Object.values(res.deleted).reduce((a, b) => a + b, 0);
      setResetMsg(`Cleared ${total} records. Re-sync your connectors to pull real data.`);
      setConfirming(false);
    } catch {
      setResetMsg("Couldn't reset — please try again.");
    } finally {
      setResetting(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Settings</h1>
          <p>Workspace configuration, data governance, and advanced tooling.</p>
        </div>
      </div>

      <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}>
        {LINKS.map((link) => {
          const Icon = link.icon;
          return (
            <Link key={link.href} href={link.href} className="card" style={{ textDecoration: "none" }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
                <div
                  className="connector-icon-badge"
                  style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
                >
                  <Icon size={18} strokeWidth={1.75} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                    <h2 style={{ margin: 0 }}>{link.title}</h2>
                    <ChevronRight size={14} style={{ marginLeft: "auto", color: "var(--text-muted)" }} />
                  </div>
                  <p className="meta" style={{ margin: 0, lineHeight: 1.5 }}>
                    {link.description}
                  </p>
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      {/* Danger zone — clear seeded/ingested content */}
      <div
        className="card"
        style={{ marginTop: 28, borderColor: "color-mix(in srgb, var(--red) 35%, var(--border))" }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
          <div
            className="connector-icon-badge"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--red)" }}
          >
            <Trash2 size={18} strokeWidth={1.75} />
          </div>
          <div style={{ flex: 1 }}>
            <h2 style={{ margin: 0 }}>Reset workspace data</h2>
            <p className="meta" style={{ margin: "4px 0 12px", lineHeight: 1.5 }}>
              Delete all indexed documents, decisions, workflows and sample data. Your connected
              tools stay connected — just click “Sync now” afterwards to pull your real data back in.
            </p>
            {resetMsg && (
              <p className="success-text" style={{ marginBottom: 10 }}>{resetMsg}</p>
            )}
            {confirming ? (
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button className="btn btn-danger" onClick={handleReset} disabled={resetting}>
                  {resetting ? "Clearing…" : "Yes, clear everything"}
                </button>
                <button className="btn" onClick={() => setConfirming(false)} disabled={resetting}>
                  Cancel
                </button>
              </div>
            ) : (
              <button className="btn btn-danger" onClick={() => setConfirming(true)}>
                Clear workspace data
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
