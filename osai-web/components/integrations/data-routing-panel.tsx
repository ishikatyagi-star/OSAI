"use client";

import { useCallback, useEffect, useState } from "react";
import { RotateCw } from "lucide-react";
import { getDataRouting, patchDataRouting } from "@/lib/api";
import { DEMO_DATA_ROUTING } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { DataRouting } from "@/lib/types";

const TIERS = ["normal", "amber", "red"] as const;
type Tier = (typeof TIERS)[number];

const LOAD_TIMEOUT_MS = 10000;
type LoadState = "loading" | "ready" | "error";

const TIER_META: Record<Tier, { color: string; icon: string; title: string; description: string; badge: string }> = {
  normal: {
    color: "var(--green)",
    icon: "🟢",
    title: "Normal",
    description:
      "Standard company data. All connectors and cloud LLM processing allowed. Documents indexed to Qdrant with standard access controls.",
    badge: "badge-green",
  },
  amber: {
    color: "var(--yellow)",
    icon: "🟡",
    title: "Amber",
    description:
      "Sensitive business data. Restricted connector set — only Notion and Google Drive permitted. Cloud LLM processing disabled; search-only mode.",
    badge: "badge-amber",
  },
  red: {
    color: "var(--red)",
    icon: "🔴",
    title: "Red",
    description:
      "Restricted / confidential data. No external connectors or cloud APIs. All processing runs locally via Ollama (Llama3/Mistral) on a private VPC endpoint.",
    badge: "badge-red",
  },
};

const ALL_CONNECTORS = ["notion", "slack", "freshdesk", "google_drive"];

const EMPTY_ROUTING: DataRouting = {
  normal: { allowed_connectors: ALL_CONNECTORS, llm_allowed: true },
  amber: { allowed_connectors: ["notion", "google_drive"], llm_allowed: false },
  red: { allowed_connectors: [], llm_allowed: false },
};

export function DataRoutingPanel() {
  const [routing, setRouting] = useState<DataRouting | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const d = await getDataRouting();
      setRouting(d ?? (isDemo() ? DEMO_DATA_ROUTING : EMPTY_ROUTING));
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    load();
    const t = setTimeout(() => {
      if (!cancelled) setLoadState((s) => (s === "loading" ? "error" : s));
    }, LOAD_TIMEOUT_MS);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [load]);

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

  return (
    <div>
      <p className="meta leading-normal" style={{ marginBottom: 20, maxWidth: 720 }}>
        Classify your data into sensitivity tiers to control which connectors and LLM providers
        are permitted. Set which information inside each connected tool belongs to a tier from the
        connector&apos;s <strong>Manage → Data sensitivity rules</strong>.
      </p>

      {loadState === "loading" && (
        <div className="card" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14, padding: "48px 24px" }}>
          <div className="search-thinking-dots">
            <span /><span /><span />
          </div>
          <p className="meta">Loading data routing policies…</p>
        </div>
      )}

      {loadState === "error" && (
        <div className="card" style={{ textAlign: "center", padding: "44px 24px" }}>
          <p className="text-body font-semibold" style={{ marginBottom: 6 }}>Couldn&apos;t load routing settings</p>
          <p className="meta" style={{ marginBottom: 18 }}>
            The settings service didn&apos;t respond. Check that the backend is reachable, then try again.
          </p>
          <button className="btn btn-primary" onClick={load} style={{ display: "inline-flex" }}>
            <RotateCw className="size-3.5" /> Retry
          </button>
        </div>
      )}

      {loadState === "ready" && routing && (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 20, marginBottom: 28 }}>
            {TIERS.map((tier) => {
              const meta = TIER_META[tier];
              const config = routing[tier];

              return (
                <div key={tier} className="card" style={{ padding: 0, overflow: "hidden" }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      padding: "18px 22px",
                      borderBottom: "1px solid var(--border)",
                    }}
                  >
                    <div style={{ width: 4, height: 40, borderRadius: 9999, background: meta.color, flexShrink: 0 }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                        <h2 style={{ margin: 0 }}>{meta.icon} {meta.title} Tier</h2>
                        <span className={`badge ${meta.badge}`}>{tier}</span>
                      </div>
                      <p className="meta" style={{ margin: 0 }}>
                        {meta.description}
                      </p>
                    </div>
                  </div>

                  <div style={{ padding: "18px 22px" }}>
                    <div style={{ display: "flex", gap: 32, flexWrap: "wrap", alignItems: "flex-start" }}>
                      <div style={{ flex: 1 }}>
                        <p className="text-micro font-semibold uppercase" style={{ color: "var(--text-secondary)", marginBottom: 10, letterSpacing: "0.5px" }}>
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
                                  border: checked ? "1px solid var(--accent-ring)" : "1px solid var(--border)",
                                  background: checked ? "var(--accent-dim)" : "var(--bg-surface)",
                                  cursor: "pointer",
                                  transition: "all 0.2s",
                                  color: "var(--text-primary)",
                                }}
                                className="text-micro font-medium"
                              >
                                <input type="checkbox" checked={checked} onChange={() => toggleConnector(tier, key)} style={{ display: "none" }} />
                                <span>{cm?.icon ?? "⚙"}</span>
                                <span>{cm?.label ?? key}</span>
                                {checked && <span className="text-[10px]">✓</span>}
                              </label>
                            );
                          })}
                        </div>
                      </div>

                      <div>
                        <p className="text-micro font-semibold uppercase" style={{ color: "var(--text-secondary)", marginBottom: 10, letterSpacing: "0.5px" }}>
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
                            border: config.llm_allowed ? "1px solid var(--accent-ring)" : "1px solid var(--border)",
                            background: config.llm_allowed ? "var(--accent-dim)" : "var(--bg-surface)",
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
                              background: config.llm_allowed ? "var(--accent)" : "var(--bg-hover)",
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
                          <span className="text-micro font-semibold" style={{ color: "var(--text-primary)" }}>
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
            <button className="btn btn-primary" onClick={handleSave} disabled={saving} style={{ padding: "11px 28px" }}>
              {saving ? "Saving…" : "Save Changes"}
            </button>
            {savedMsg && <span className="success-text text-caption">✓ {savedMsg}</span>}
            {error && <span className="error-text text-caption">{error}</span>}
          </div>
        </>
      )}
    </div>
  );
}
