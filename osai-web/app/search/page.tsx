"use client";

import { useState } from "react";
import { postSearch } from "@/lib/api";
import { DEMO_SEARCH_ANSWERS } from "@/lib/demo-data";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { SearchResponse } from "@/lib/types";

const SUGGESTED = [
  "What are the Q3 priorities?",
  "Who is responsible for the VPC security setup?",
  "What is the onboarding process for new engineers?",
  "Any open SLA escalations in Freshdesk?",
];

function normaliseKey(q: string) {
  return q.toLowerCase().replace(/[^a-z0-9 ]/g, "").trim();
}

function getDemoAnswer(query: string): SearchResponse {
  const key = normaliseKey(query);
  for (const [k, v] of Object.entries(DEMO_SEARCH_ANSWERS)) {
    if (key.includes(k) || k.includes(key)) return v;
  }
  return DEMO_SEARCH_ANSWERS.default;
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct > 90 ? "#22c55e" : pct > 75 ? "#0099ff" : "#f5c842";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 3, background: "rgba(255,255,255,0.08)", borderRadius: 9999 }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 9999 }} />
      </div>
      <span style={{ fontSize: 11, color, fontWeight: 600, minWidth: 30 }}>{pct}%</span>
    </div>
  );
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState("");
  const [lastQuery, setLastQuery] = useState("");

  async function handleSearch(q: string) {
    const trimmed = q.trim();
    if (!trimmed) return;
    setQuery(trimmed);
    setLastQuery(trimmed);
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await postSearch(trimmed);
      setResult(res.citations?.length ? res : getDemoAnswer(trimmed));
    } catch {
      setResult(getDemoAnswer(trimmed));
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    handleSearch(query);
  }

  return (
    <div>
      <h1>Search</h1>
      <p className="page-subtitle">
        Ask anything about your company knowledge base — get a synthesised answer with inline citations
        from Notion, Slack, Google Drive, and Freshdesk.
      </p>

      {/* Search form */}
      <div className="search-container">
        <form onSubmit={handleSubmit} className="search-form" style={{ marginBottom: 16 }}>
          <input
            type="text"
            className="search-input"
            placeholder="Ask anything across your connected knowledge base…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
          <button type="submit" className="btn btn-primary" disabled={loading} style={{ padding: "12px 24px" }}>
            {loading ? (
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className="spinner" />
                Searching
              </span>
            ) : (
              "Search"
            )}
          </button>
        </form>

        {/* Suggested searches */}
        {!result && (
          <div style={{ marginBottom: 32 }}>
            <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 10, fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>
              Suggested searches
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {SUGGESTED.map((s) => (
                <button
                  key={s}
                  className="suggestion-chip"
                  onClick={() => handleSearch(s)}
                  disabled={loading}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Loading state */}
      {loading && (
        <div className="card" style={{ textAlign: "center", padding: "48px 24px" }}>
          <div style={{ marginBottom: 16 }}>
            <div className="search-thinking-dots">
              <span /><span /><span />
            </div>
          </div>
          <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>Searching across your connected knowledge base…</p>
        </div>
      )}

      {/* Error fallback */}
      {error && <p className="error-text">{error}</p>}

      {/* Results */}
      {result && !loading && (
        <div className="search-result">
          {/* Query echo */}
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>
            Results for: <span style={{ color: "var(--text-secondary)", fontStyle: "italic" }}>&ldquo;{lastQuery}&rdquo;</span>
          </p>

          {/* Answer card */}
          <div className="card answer-card" style={{ marginBottom: 24 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
              <span style={{ fontSize: 16 }}>✨</span>
              <h2 style={{ margin: 0, fontSize: 15 }}>Synthesised Answer</h2>
              {result.enough_context ? (
                <span className="badge badge-green" style={{ marginLeft: "auto", fontSize: 10 }}>High confidence</span>
              ) : (
                <span className="badge badge-yellow" style={{ marginLeft: "auto", fontSize: 10 }}>Limited context</span>
              )}
            </div>
            <div
              style={{
                whiteSpace: "pre-wrap",
                lineHeight: 1.7,
                fontSize: 14,
                color: "var(--text-primary)",
              }}
              dangerouslySetInnerHTML={{
                __html: result.answer
                  .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
                  .replace(/✅/g, "<span style='color:#22c55e'>✅</span>"),
              }}
            />
            {!result.enough_context && (
              <p className="meta" style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid rgba(255,255,255,0.06)" }}>
                ⚠ Not enough indexed context — trigger a sync from Integrations to improve coverage.
              </p>
            )}
          </div>

          {/* Citations */}
          {result.citations.length > 0 && (
            <div>
              <h2 style={{ fontSize: 14, marginBottom: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                Sources ({result.citations.length})
              </h2>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {result.citations.map((c, i) => {
                  const meta = CONNECTOR_META[c.source_tool];
                  return (
                    <div className="card citation-card" key={i} style={{ padding: "14px 18px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                        {meta && (
                          <span style={{ fontSize: 14, color: meta.color }}>{meta.icon}</span>
                        )}
                        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", flex: 1 }}>
                          {c.source_record_title}
                        </span>
                        <span className="badge badge-grey" style={{ fontSize: 10 }}>
                          {meta?.label ?? c.source_tool}
                        </span>
                      </div>
                      <ConfidenceBar value={c.confidence} />
                      {c.url && (
                        <a
                          href={c.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ display: "block", marginTop: 8, fontSize: 11, color: "#0099ff" }}
                        >
                          {c.url}
                        </a>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* New search */}
          <div style={{ marginTop: 24 }}>
            <button
              className="suggestion-chip"
              onClick={() => { setResult(null); setQuery(""); }}
            >
              ← New search
            </button>
            <span style={{ marginLeft: 12, fontSize: 12, color: "#64748b" }}>or try another suggestion above</span>
          </div>
        </div>
      )}
    </div>
  );
}
