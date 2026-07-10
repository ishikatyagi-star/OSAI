"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Clock,
  Cpu,
  RotateCw,
  XCircle,
} from "lucide-react";
import { getEvalRun } from "@/lib/api";
import { DEMO_EVAL_RUN } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import type { EvalCase, EvalCategory, EvalRun } from "@/lib/types";
import { cn } from "@/lib/utils";

const CATEGORY_LABEL: Record<EvalCategory, string> = {
  ticket_triage: "Ticket triage",
  ownership: "Ownership",
  routing: "Routing",
  qa: "Q&A",
};

// Hard cap so the page can never sit on a spinner indefinitely, even if the
// request never settles. apiGet already aborts at 8s; this is belt-and-braces.
const LOAD_TIMEOUT_MS = 10000;

type LoadState = "loading" | "ready" | "error";

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "default" | "success" | "destructive";
}) {
  return (
    <div className="stat-card">
      <p className="stat-card-label">
        {label}
      </p>
      <p
        className="stat-card-value mt-1 tabular-nums"
        style={{
          color:
            tone === "success"
              ? "var(--green)"
              : tone === "destructive"
                ? "var(--red)"
                : "var(--text-primary)",
        }}
      >
        {value}
      </p>
    </div>
  );
}

function PassRateBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  // Limited palette: green (good) / blue (acceptable) / red (failing).
  const color = pct >= 80 ? "var(--green)" : pct >= 60 ? "var(--blue)" : "var(--red)";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: 'var(--bg-hover)' }}>
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="w-9 shrink-0 text-right text-xs tabular-nums" style={{ color: 'var(--text-primary)' }}>
        {pct}%
      </span>
    </div>
  );
}

function CaseRow({ c }: { c: EvalCase }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 20, padding: 0, overflow: 'hidden' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
        style={{
          alignItems: "center",
          background: "transparent",
          border: "none",
          color: "var(--text-primary)",
          cursor: "pointer",
          display: "flex",
          gap: 12,
          minHeight: 44,
          padding: "12px 16px",
          width: "100%",
        }}
      >
        {c.passed ? (
          <CheckCircle2 className="size-4 shrink-0" style={{ color: 'var(--green)' }} />
        ) : (
          <XCircle className="size-4 shrink-0" style={{ color: 'var(--red)' }} />
        )}
        <span className="min-w-0 flex-1 truncate text-sm" style={{ color: 'var(--text-primary)' }}>
          {c.question}
        </span>
        <span className="badge badge-grey hidden sm:inline-flex">
          {CATEGORY_LABEL[c.category]}
        </span>
        <span className="hidden w-14 shrink-0 text-right text-xs tabular-nums md:inline" style={{ color: 'var(--text-primary)' }}>
          {c.score.toFixed(2)}
        </span>
        <span className="hidden w-16 shrink-0 items-center justify-end gap-1 text-xs tabular-nums md:flex" style={{ color: 'var(--text-primary)' }}>
          <Clock className="size-3" />
          {(c.latency_ms / 1000).toFixed(2)}s
        </span>
        <ChevronDown
          className={cn(
            "size-4 shrink-0 transition-transform",
            open && "rotate-180"
          )}
          style={{ color: 'var(--text-primary)' }}
        />
      </button>
      {open && (
        <div className="grid gap-3 border-t border-border px-4 py-3 sm:grid-cols-2">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: 'var(--text-primary)' }}>
              Expected
            </p>
            <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>{c.expected}</p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: 'var(--text-primary)' }}>
              Actual
            </p>
            <p
              className="mt-1 text-sm"
              style={{ color: c.passed ? 'var(--text-secondary)' : 'var(--red)' }}
            >
              {c.actual}
            </p>
          </div>
          {c.notes && (
            <div className="sm:col-span-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: 'var(--text-primary)' }}>
                Notes
              </p>
              <p className="mt-1 text-sm" style={{ color: "#6f4d12" }}>{c.notes}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function EvalDashboard() {
  const [run, setRun] = useState<EvalRun | null>(null);
  const [usingDemo, setUsingDemo] = useState(false);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [filter, setFilter] = useState<EvalCategory | "all">("all");

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const res = await getEvalRun();
      if (res) {
        setRun(res);
        setUsingDemo(false);
      } else if (isDemo()) {
        // No backend reachable, demo mode on - show the bundled demo run.
        setRun(DEMO_EVAL_RUN);
        setUsingDemo(true);
      } else {
        setRun({
          run_id: "",
          created_at: "",
          model_route: "",
          pass_rate: 0,
          total: 0,
          passed: 0,
          failed: 0,
          cases: [],
        });
        setUsingDemo(false);
      }
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

  const categoryStats = useMemo(() => {
    if (!run) return [];
    const map = new Map<EvalCategory, { total: number; passed: number }>();
    for (const c of run.cases) {
      const s = map.get(c.category) ?? { total: 0, passed: 0 };
      s.total += 1;
      if (c.passed) s.passed += 1;
      map.set(c.category, s);
    }
    return Array.from(map.entries()).map(([category, s]) => ({
      category,
      ...s,
      rate: s.total ? s.passed / s.total : 0,
    }));
  }, [run]);

  const visibleCases = useMemo(() => {
    if (!run) return [];
    if (filter === "all") return run.cases;
    return run.cases.filter((c) => c.category === filter);
  }, [run, filter]);

  const isEmpty = loadState === "ready" && run != null && run.cases.length === 0;
  const hasData = loadState === "ready" && run != null && run.cases.length > 0;

  return (
    <div id="evals" className="pb-10">
      <div className="page-header">
        <div className="page-header-left">
          <h1>Evals</h1>
          <p>Quality and regression tracking for Sheldon AI&apos;s answers and routing.</p>
        </div>
        {hasData && run && (
          <div className="page-header-meta">
            <span className="inline-flex items-center gap-1">
              <Cpu className="size-3" />
              {run.model_route}
            </span>
            <span className="sep">·</span>
            <span className="font-mono">{run.run_id}</span>
            {usingDemo && <span className="badge badge-grey">demo data</span>}
          </div>
        )}
      </div>

      {/* Loading */}
      {loadState === "loading" && (
        <div className="card" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14, padding: "48px 24px" }}>
          <div className="search-thinking-dots">
            <span /><span /><span />
          </div>
          <p className="meta">Loading the latest eval run…</p>
        </div>
      )}

      {/* Error + retry */}
      {loadState === "error" && (
        <div className="card" style={{ textAlign: "center", padding: "44px 24px" }}>
          <p className="text-[15px] font-semibold" style={{ marginBottom: 6 }}>Couldn&apos;t load eval results</p>
          <p className="meta" style={{ marginBottom: 18 }}>
            The eval service didn&apos;t respond. Check that the backend is reachable, then try again.
          </p>
          <button className="btn btn-primary" onClick={load} style={{ display: "inline-flex" }}>
            <RotateCw className="size-3.5" /> Retry
          </button>
        </div>
      )}

      {/* Empty (reached backend, no cases yet) */}
      {isEmpty && (
        <div className="card" style={{ textAlign: "center", padding: "44px 24px" }}>
          <p className="text-[15px] font-semibold" style={{ marginBottom: 6 }}>No eval cases yet</p>
          <p className="meta" style={{ maxWidth: 420, margin: "0 auto" }}>
            Once the eval suite runs against your indexed data, pass rates and per-case results
            will appear here.
          </p>
        </div>
      )}

      {/* Data */}
      {hasData && run && (
        <>
          {/* Summary */}
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard
              label="Pass rate"
              value={`${Math.round(run.pass_rate * 100)}%`}
              tone={run.pass_rate >= 0.8 ? "success" : "destructive"}
            />
            <StatCard label="Total cases" value={String(run.total)} />
            <StatCard label="Passed" value={String(run.passed)} tone="success" />
            <StatCard label="Failed" value={String(run.failed)} tone={run.failed > 0 ? "destructive" : "default"} />
          </div>

          {/* Category breakdown */}
          <div className="card" style={{ marginTop: 16, padding: '20px 22px' }}>
            <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: 'var(--text-primary)' }}>
              By category
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {categoryStats.map((s) => (
                <div key={s.category} className="space-y-1">
                  <div className="flex items-center justify-between text-sm">
                    <span style={{ color: 'var(--text-primary)' }}>
                      {CATEGORY_LABEL[s.category]}
                    </span>
                    <span className="text-xs tabular-nums" style={{ color: 'var(--text-primary)' }}>
                      {s.passed}/{s.total}
                    </span>
                  </div>
                  <PassRateBar rate={s.rate} />
                </div>
              ))}
            </div>
          </div>

          {/* Cases */}
          <div className="mt-6">
            <div role="tablist" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button role="tab" aria-selected={filter === "all"} className={`suggestion-chip${filter === "all" ? " active" : ""}`} onClick={() => setFilter("all")}>All</button>
              {(Object.keys(CATEGORY_LABEL) as EvalCategory[]).map((c) => (
                <button key={c} role="tab" aria-selected={filter === c} className={`suggestion-chip${filter === c ? " active" : ""}`} onClick={() => setFilter(c)}>{CATEGORY_LABEL[c]}</button>
              ))}
            </div>

            <div className="mt-4 space-y-2">
              {visibleCases.map((c) => (
                <CaseRow key={c.id} c={c} />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
