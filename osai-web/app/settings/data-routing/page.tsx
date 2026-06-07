"use client";

import { useEffect, useState } from "react";
import { getDataRouting, patchDataRouting } from "@/lib/api";
import { DEMO_DATA_ROUTING } from "@/lib/demo-data";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { DataRouting } from "@/lib/types";

const TIERS = ["normal", "amber", "red"] as const;
type Tier = (typeof TIERS)[number];

const TIER_META: Record<Tier, { color: string; icon: string; title: string; description: string; badge: string }> = {
  normal: {
    color: "#4ade80",
    icon: "🟢",
    title: "Normal",
    description:
      "Standard company data. All connectors and cloud LLM processing allowed. Documents indexed to Qdrant with standard access controls.",
    badge: "badge-green",
  },
  amber: {
    color: "#fb923c",
    icon: "🟡",
    title: "Amber",
    description:
      "Sensitive business data. Restricted connector set — only Notion and Google Drive permitted. Cloud LLM processing disabled; search-only mode.",
    badge: "badge-amber",
  },
  red: {
    color: "#f87171",
    icon: "🔴",
    title: "Red",
    description:
      "Restricted / confidential data. No external connectors or cloud APIs. All processing runs locally via Ollama (Llama3/Mistral) on a private VPC endpoint.",
    badge: "badge-red",
  },
};

const ALL_CONNECTORS = ["notion", "slack", "freshdesk", "google_drive"];

export default function DataRoutingPage() {
  const [routing, setRouting] = useState<DataRouting | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    getDataRouting().then((d) => setRouting(d ?? DEMO_DATA_ROUTING));
  }, []);

  async function handleSave() {
    if (!routing) return;
    setSaving(true);
    setError("");
    setSavedMsg("");
    try {
      const updated = await patchDataRouting(routing);
      setRouting(updated);
      setSavedMsg("Settings saved.");
    } catch {
      setSavedMsg("Saved (demo mode).");
    } finally {
      setSaving(false);
      setTimeout(() => setSavedMsg(""), 3000);
    }
  }

  function toggleConnector(tier: Tier, connector: string) {
    if (!routing) return;
    const current = routing[tier].allowed_connectors;
    const next = current.includes(connector)
      ? current.filter((c) => c !== connector)
      : [...current, connector];
    setRouting({ ...routing, [tier]: { ...routing[tier], allowed_connectors: next } });
  }

  function toggleLlm(tier: Tier) {
    if (!routing) return;
    setRouting({ ...routing, [tier]: { ...routing[tier], llm_allowed: !routing[tier].llm_allowed } });
  }

  if (!routing) {
    return (
      <div>
        <h1>Data Routing</h1>
        <p className="meta">Loading…</p>
      </div>
    );
  }

  return (
    <div>
      <h1>Data Routing</h1>
      <p className="page-subtitle">
        Classify your data into sensitivity tiers to control which connectors and LLM providers
        are permitted. Ensures compliance with internal data governance policies.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 20, marginBottom: 28 }}>
        {TIERS.map((tier) => {
          const meta = TIER_META[tier];
          const config = routing[tier];

          return (
            <div
              key={tier}
              className="card"
              style={{ borderColor: `${meta.color}20`, padding: 0, overflow: "hidden" }}
            >
              {/* Tier header */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  padding: "18px 22px",
                  background: `${meta.color}06`,
                  borderBottom: "1px solid rgba(255,255,255,0.05)",
                }}
              >
                <div
                  style={{
                    width: 4,
                    height: 40,
                    borderRadius: 9999,
                    background: meta.color,
                    flexShrink: 0,
                  }}
                />
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                    <h2 style={{ margin: 0, fontSize: 16 }}>{meta.icon} {meta.title} Tier</h2>
                    <span className={`badge ${meta.badge}`}>{tier}</span>
                  </div>
                  <p className="meta" style={{ margin: 0, fontSize: 12, lineHeight: 1.4 }}>
                    {meta.description}
                  </p>
                </div>
              </div>

              {/* Controls */}
              <div style={{ padding: "18px 22px" }}>
                <div style={{ display: "flex", gap: 32, flexWrap: "wrap", alignItems: "flex-start" }}>
                  {/* Connector toggles */}
                  <div style={{ flex: 1 }}>
                    <p style={{ fontWeight: 600, fontSize: 12, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 10 }}>
                      Allowed Connectors
                    </p>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                      {ALL_CONNECTORS.map((key) => {
                        const cm = CONNECTOR_META[key];
                        const checked = config.allowed_connectors.includes(key);
                        return (
                          <label
                            key={key}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 7,
                              padding: "7px 14px",
                              borderRadius: 8,
                              border: `1px solid ${checked ? `${cm?.color ?? meta.color}30` : "rgba(255,255,255,0.07)"}`,
                              background: checked ? `${cm?.color ?? meta.color}0d` : "rgba(255,255,255,0.02)",
                              cursor: "pointer",
                              transition: "all 0.2s",
                              fontSize: 12,
                              fontWeight: 500,
                              color: checked ? (cm?.color ?? meta.color) : "#64748b",
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleConnector(tier, key)}
                              style={{ display: "none" }}
                            />
                            <span>{cm?.icon ?? "⚙"}</span>
                            <span>{cm?.label ?? key}</span>
                            {checked && <span style={{ color: "#4ade80", fontSize: 10 }}>✓</span>}
                          </label>
                        );
                      })}
                    </div>
                  </div>

                  {/* LLM toggle */}
                  <div>
                    <p style={{ fontWeight: 600, fontSize: 12, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 10 }}>
                      LLM Processing
                    </p>
                    <label
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        cursor: "pointer",
                        padding: "7px 14px",
                        borderRadius: 8,
                        border: `1px solid ${config.llm_allowed ? "rgba(96,165,250,0.25)" : "rgba(255,255,255,0.07)"}`,
                        background: config.llm_allowed ? "rgba(96,165,250,0.07)" : "rgba(255,255,255,0.02)",
                        transition: "all 0.2s",
                        minWidth: 160,
                      }}
                    >
                      <input type="checkbox" checked={config.llm_allowed} onChange={() => toggleLlm(tier)} style={{ display: "none" }} />
                      <div
                        style={{
                          width: 32,
                          height: 18,
                          borderRadius: 9999,
                          background: config.llm_allowed ? "#60a5fa" : "rgba(255,255,255,0.1)",
                          position: "relative",
                          transition: "background 0.2s",
                          flexShrink: 0,
                        }}
                      >
                        <div
                          style={{
                            position: "absolute",
                            top: 2,
                            left: config.llm_allowed ? 16 : 2,
                            width: 14,
                            height: 14,
                            borderRadius: "50%",
                            background: "#fff",
                            transition: "left 0.2s",
                          }}
                        />
                      </div>
                      <span style={{ fontSize: 12, fontWeight: 600, color: config.llm_allowed ? "#93c5fd" : "#64748b" }}>
                        {config.llm_allowed ? "Allowed" : "Disabled"}
                      </span>
                    </label>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <button
          className="btn btn-primary"
          onClick={handleSave}
          disabled={saving}
          style={{ padding: "11px 28px" }}
        >
          {saving ? "Saving…" : "Save Changes"}
        </button>
        {savedMsg && <span className="success-text" style={{ fontSize: 13 }}>✓ {savedMsg}</span>}
        {error && <span className="error-text" style={{ fontSize: 13 }}>{error}</span>}
      </div>
    </div>
  );
}
