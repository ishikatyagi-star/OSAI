"use client";

import { AlertTriangle } from "lucide-react";
import type { AgentAction, AskUiArtifact, SourceCitation } from "@/lib/types";
import { MarkdownLite } from "./markdown-lite";
import { CitationChip } from "./citation-chip";
import { ActionCard } from "./action-card";
import { OpenUiArtifacts } from "./openui-artifacts";
import { FeedbackButtons } from "./feedback-buttons";
import { FileCard, type UploadedFile } from "./file-card";
import { brandText } from "@/lib/utils";

export type AskTurn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  // The user question this assistant turn answered (for feedback capture).
  question?: string;
  conversationId?: string | null;
  citations?: SourceCitation[];
  actions?: AgentAction[];
  enoughContext?: boolean;
  modelRoute?: string;
  latencyMs?: number;
  artifacts?: AskUiArtifact[];
  // Files uploaded from the composer, rendered as cards with a ⋯ access menu.
  files?: UploadedFile[];
};

export function MessageBubble({
  turn,
  busyActions,
  onApprove,
  onDismiss,
}: {
  turn: AskTurn;
  busyActions?: Record<string, "approve" | "dismiss">;
  onApprove: (turnId: string, action: AgentAction) => void;
  onDismiss: (turnId: string, action: AgentAction) => void;
}) {
  if (turn.role === "user") {
    return (
      <div className="ask-user-turn flex justify-end">
        <div className="ask-user-bubble max-w-[72%]">
          {turn.content}
        </div>
      </div>
    );
  }

  return (
    <div className="ask-assistant-turn flex gap-3">
      <div
        className="ask-turn-avatar flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-extrabold text-primary-foreground"
        aria-hidden
      >
        O
      </div>
      <div className="ask-turn-body min-w-0 flex-1 space-y-4">
        <div className="ask-assistant-bubble">
          <MarkdownLite text={brandText(turn.content)} />
        </div>

        {turn.enoughContext === false && (
          <div className="ask-context-notice" role="note">
            <AlertTriangle className="size-4 shrink-0" strokeWidth={1.8} />
            <span>
              Limited workspace context. Sync your integrations for a more complete answer.
            </span>
          </div>
        )}

        {turn.citations && turn.citations.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Sources ({turn.citations.length})
            </p>
            <div className="ask-citations flex flex-wrap gap-1.5">
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
                busyOperation={busyActions?.[a.id] ?? null}
                onApprove={(action) => onApprove(turn.id, action)}
                onDismiss={(action) => onDismiss(turn.id, action)}
              />
            ))}
          </div>
        )}

        <OpenUiArtifacts artifacts={turn.artifacts} />

        {turn.files && turn.files.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {turn.files.map((f) => (
              <FileCard key={f.id} file={f} />
            ))}
          </div>
        )}

        {turn.question && (
          <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
            <FeedbackButtons
              question={turn.question}
              answer={turn.content}
              conversationId={turn.conversationId}
              citations={turn.citations}
              modelRoute={turn.modelRoute}
            />
          </div>
        )}
      </div>
    </div>
  );
}
