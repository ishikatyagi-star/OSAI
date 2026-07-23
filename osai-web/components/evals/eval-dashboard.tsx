"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Clock,
  Cpu,
  Play,
  RotateCw,
  XCircle,
} from "lucide-react";
import { ApiError, getSession, runEvalSuite } from "@/lib/api";
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

type LoadState = "checking" | "idle" | "running" | "ready" | "error" | "forbidden";

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
      <div
        className="h-1.5 w-full overflow-hidden rounded-full"
        style={{ background: 'var(--bg-hover)' }}
        role="progressbar"
        aria-label="Pass rate"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <div
          className="h-full rounded-full transition-[width,background-color]"
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
        aria-expanded={open}
        aria-controls={`eval-case-${c.id}`}
      >
        {c.passed ? (
          <CheckCircle2 className="size-4 shrink-0" style={{ color: 'var(--green)' }} />
        ) : (
          <XCircle className="size-4 shrink-0" style={{ color: 'var(--red)' }} />
        )}
        <span className={`badge ${c.passed ? "badge-green" : "badge-red"}`}>
          {c.passed ? "Passed" : "Failed"}
        </span>
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
        <div id={`eval-case-${c.id}`} className="grid gap-3 border-t border-border px-4 py-3 sm:grid-cols-2">
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
  const [isAdmin, setIsAdmin] = useState(false);
  const [loadState, setLoadState] = useState<LoadState>("checking");
  const [filter, setFilter] = useState<EvalCategory | "all">("all");

  const prepare = useCallback(async () => {
    setLoadState("checking");
    try {
      if (isDemo()) {
        setRun(DEMO_EVAL_RUN);
        setUsingDemo(true);
        setLoadState("ready");
        return;
      }
      const session = await getSession(true);
      const admin = Boolean(session?.is_admin);
      setIsAdmin(admin);
      setUsingDemo(false);
      setLoadState(admin ? "idle" : "forbidden");
    } catch (error) {
      if (error instanceof Error && /\((?:401|403)\)/.test(error.message)) {
        setIsAdmin(false);
        setLoadState("forbidden");
        return;
      }
      setLoadState("error");
    }
  }, []);

  const runSuite = useCallback(async () => {
    setLoadState("running");
    try {
      const result = await runEvalSuite();
      setRun(result);
      setUsingDemo(false);
      setLoadState("ready");
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        setIsAdmin(false);
        await prepare();
        return;
      }
      setLoadState("error");
    }
  }, [prepare]);

  useEffect(() => {
    prepare();
  }, [prepare]);

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
          <p>Quality and regression tracking for Sheldon&apos;s answers and routing.</p>
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
        {loadState === "ready" && isAdmin && !usingDemo && (
          <button type="button" className="btn btn-secondary" onClick={runSuite}>
            <RotateCw className="size-3.5" aria-hidden="true" /> Run again
          </button>
        )}
      </div>

      {/* Session check */}
      {loadState === "checking" && (
        <div className="card async-state" role="status" aria-live="polite">
          <div className="search-thinking-dots">
            <span /><span /><span />
          </div>
          <p className="meta">Checking eval access…</p>
        </div>
      )}

      {/* Page loads never trigger the costly model calls. */}
      {loadState === "idle" && (
        <div className="card" style={{ textAlign: "center", padding: "44px 24px" }}>
          <p className="text-[15px] font-semibold" style={{ marginBottom: 6 }}>Run the evaluation suite</p>
          <p className="meta" style={{ maxWidth: 520, margin: "0 auto 18px" }}>
            This runs live model calls against the fixture suite and may incur provider cost.
            Results are returned when the run finishes.
          </p>
          <button type="button" className="btn btn-primary" onClick={runSuite}>
            <Play className="size-3.5" aria-hidden="true" /> Run eval suite
          </button>
        </div>
      )}

      {loadState === "running" && (
        <div className="card async-state" role="status" aria-live="polite">
          <div className="search-thinking-dots">
            <span /><span /><span />
          </div>
          <p className="meta">Running live evaluations. This can take a few minutes…</p>
        </div>
      )}

      {loadState === "forbidden" && (
        <div className="card" role="alert" style={{ textAlign: "center", padding: "40px 24px" }}>
          <p className="text-[15px] font-semibold" style={{ marginBottom: 6 }}>Admin access required</p>
          <p className="meta">Only current workspace admins can run live evaluations.</p>
        </div>
      )}

      {/* Error + retry */}
      {loadState === "error" && (
        <div className="card" role="alert" style={{ textAlign: "center", padding: "40px 24px" }}>
          <p className="text-[15px] font-semibold" style={{ marginBottom: 6 }}>Couldn&apos;t complete the eval request</p>
          <p className="meta" style={{ marginBottom: 18 }}>
            The service didn&apos;t respond or the run failed. Check the backend, then try again.
          </p>
          <button type="button" className="btn btn-primary" onClick={isAdmin ? runSuite : prepare} style={{ display: "inline-flex" }}>
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
            <div role="group" aria-label="Filter eval cases" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" aria-pressed={filter === "all"} className={`suggestion-chip${filter === "all" ? " active" : ""}`} onClick={() => setFilter("all")}>All</button>
              {(Object.keys(CATEGORY_LABEL) as EvalCategory[]).map((c) => (
                <button type="button" key={c} aria-pressed={filter === c} className={`suggestion-chip${filter === c ? " active" : ""}`} onClick={() => setFilter(c)}>{CATEGORY_LABEL[c]}</button>
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
