"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Clock,
  Cpu,
  FlaskConical,
  XCircle,
} from "lucide-react";
import { getEvalRun } from "@/lib/api";
import { DEMO_EVAL_RUN } from "@/lib/demo-data";
import type { EvalCase, EvalCategory, EvalRun } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const CATEGORY_LABEL: Record<EvalCategory, string> = {
  ticket_triage: "Ticket triage",
  ownership: "Ownership",
  routing: "Routing",
  qa: "Q&A",
};

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
    <Card className="p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-2xl font-semibold tabular-nums",
          tone === "success" && "text-success",
          tone === "destructive" && "text-destructive",
          (!tone || tone === "default") && "text-foreground"
        )}
      >
        {value}
      </p>
    </Card>
  );
}

function PassRateBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const color = pct >= 80 ? "#00c896" : pct >= 60 ? "#f5c842" : "#ff4d4d";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="w-9 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        {pct}%
      </span>
    </div>
  );
}

function CaseRow({ c }: { c: EvalCase }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        {c.passed ? (
          <CheckCircle2 className="size-4 shrink-0 text-success" />
        ) : (
          <XCircle className="size-4 shrink-0 text-destructive" />
        )}
        <span className="min-w-0 flex-1 truncate text-sm text-foreground">
          {c.question}
        </span>
        <Badge variant="muted" className="hidden sm:inline-flex">
          {CATEGORY_LABEL[c.category]}
        </Badge>
        <span className="hidden w-14 shrink-0 text-right text-xs tabular-nums text-muted-foreground md:inline">
          {c.score.toFixed(2)}
        </span>
        <span className="hidden w-16 shrink-0 items-center justify-end gap-1 text-xs tabular-nums text-muted-foreground md:flex">
          <Clock className="size-3" />
          {(c.latency_ms / 1000).toFixed(2)}s
        </span>
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180"
          )}
        />
      </button>
      {open && (
        <div className="grid gap-3 border-t border-border px-4 py-3 sm:grid-cols-2">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Expected
            </p>
            <p className="mt-1 text-sm text-foreground/90">{c.expected}</p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Actual
            </p>
            <p
              className={cn(
                "mt-1 text-sm",
                c.passed ? "text-foreground/90" : "text-destructive"
              )}
            >
              {c.actual}
            </p>
          </div>
          {c.notes && (
            <div className="sm:col-span-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Notes
              </p>
              <p className="mt-1 text-sm text-warning">{c.notes}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function EvalsPage() {
  const [run, setRun] = useState<EvalRun | null>(null);
  const [usingDemo, setUsingDemo] = useState(false);
  const [filter, setFilter] = useState<EvalCategory | "all">("all");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await getEvalRun();
      if (cancelled) return;
      if (!res) {
        setRun(DEMO_EVAL_RUN);
        setUsingDemo(true);
      } else {
        setRun(res);
        setUsingDemo(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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

  if (!run) {
    return (
      <div className="flex h-[60vh] items-center justify-center text-sm text-muted-foreground">
        Loading eval run…
      </div>
    );
  }

  return (
    <div className="pb-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2">
            <FlaskConical className="size-5 text-primary" />
            Eval Dashboard
          </h1>
          <p className="page-subtitle" style={{ marginBottom: 0 }}>
            Quality and regression tracking for OSAI&apos;s answers and routing.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Cpu className="size-3" />
            {run.model_route}
          </span>
          <span className="text-border">·</span>
          <span className="font-mono">{run.run_id}</span>
          {usingDemo && <Badge variant="muted">demo data</Badge>}
        </div>
      </div>

      {/* Summary */}
      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Pass rate"
          value={`${Math.round(run.pass_rate * 100)}%`}
          tone={run.pass_rate >= 0.8 ? "success" : "destructive"}
        />
        <StatCard label="Total cases" value={String(run.total)} />
        <StatCard label="Passed" value={String(run.passed)} tone="success" />
        <StatCard label="Failed" value={String(run.failed)} tone="destructive" />
      </div>

      {/* Category breakdown */}
      <Card className="mt-4 p-4">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          By category
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {categoryStats.map((s) => (
            <div key={s.category} className="space-y-1">
              <div className="flex items-center justify-between text-sm">
                <span className="text-foreground/90">
                  {CATEGORY_LABEL[s.category]}
                </span>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {s.passed}/{s.total}
                </span>
              </div>
              <PassRateBar rate={s.rate} />
            </div>
          ))}
        </div>
      </Card>

      {/* Cases */}
      <div className="mt-6">
        <Tabs
          value={filter}
          onValueChange={(v) => setFilter(v as EvalCategory | "all")}
        >
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            {(Object.keys(CATEGORY_LABEL) as EvalCategory[]).map((c) => (
              <TabsTrigger key={c} value={c}>
                {CATEGORY_LABEL[c]}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <div className="mt-4 space-y-2">
          {visibleCases.map((c) => (
            <CaseRow key={c.id} c={c} />
          ))}
        </div>
      </div>
    </div>
  );
}
