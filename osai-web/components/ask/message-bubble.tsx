"use client";

import * as React from "react";
import { Clock, Cpu } from "lucide-react";
import type { AgentAction, SourceCitation } from "@/lib/types";
import { MarkdownLite } from "./markdown-lite";
import { CitationChip } from "./citation-chip";
import { ActionCard } from "./action-card";
import { cn } from "@/lib/utils";

export type AskTurn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: SourceCitation[];
  actions?: AgentAction[];
  enoughContext?: boolean;
  modelRoute?: string;
  latencyMs?: number;
};

export function MessageBubble({
  turn,
  busyActionId,
  onApprove,
  onDismiss,
}: {
  turn: AskTurn;
  busyActionId?: string | null;
  onApprove: (turnId: string, action: AgentAction) => void;
  onDismiss: (turnId: string, action: AgentAction) => void;
}) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-xl rounded-br-sm border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-2.5 text-sm text-foreground">
          {turn.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div
        className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-extrabold text-primary-foreground"
        aria-hidden
      >
        O
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        <div className="rounded-xl rounded-tl-sm border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-3">
          <MarkdownLite text={turn.content} />

          {turn.enoughContext === false && (
            <p className="mt-3 border-t border-border pt-2.5 text-xs text-warning">
              ⚠ Limited indexed context — trigger a sync from Integrations to improve coverage.
            </p>
          )}
        </div>

        {turn.citations && turn.citations.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Sources ({turn.citations.length})
            </p>
            <div className="flex flex-wrap gap-1.5">
              {turn.citations.map((c, i) => (
                <CitationChip key={i} citation={c} index={i} />
              ))}
            </div>
          </div>
        )}

        {turn.actions && turn.actions.length > 0 && (
          <div className="space-y-2">
            {turn.actions.map((a) => (
              <ActionCard
                key={a.id}
                action={a}
                busy={busyActionId === a.id}
                onApprove={(action) => onApprove(turn.id, action)}
                onDismiss={(action) => onDismiss(turn.id, action)}
              />
            ))}
          </div>
        )}

        {(turn.modelRoute || turn.latencyMs != null) && (
          <div
            className={cn(
              "flex items-center gap-3 text-[11px] text-muted-foreground"
            )}
          >
            {turn.modelRoute && (
              <span className="inline-flex items-center gap-1">
                <Cpu className="size-3" /> {turn.modelRoute}
              </span>
            )}
            {turn.latencyMs != null && (
              <span className="inline-flex items-center gap-1">
                <Clock className="size-3" /> {(turn.latencyMs / 1000).toFixed(2)}s
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
