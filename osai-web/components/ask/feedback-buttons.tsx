"use client";

import { useState } from "react";
import { Check, ThumbsDown, ThumbsUp } from "lucide-react";
import { submitFeedback } from "@/lib/api";
import { isDemo } from "@/lib/demo";
import type { SourceCitation } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Thumbs up/down on an assistant answer. A down-vote opens a one-line comment
 * box. Each verdict is stored with the answer's retrieval trace (citations,
 * scores, model route) so it doubles as an eval dataset for retrieval work. */
export function FeedbackButtons({
  question,
  answer,
  conversationId,
  citations,
  modelRoute,
}: {
  question: string;
  answer: string;
  conversationId?: string | null;
  citations?: SourceCitation[];
  modelRoute?: string;
}) {
  const [sent, setSent] = useState<"up" | "down" | null>(null);
  const [askComment, setAskComment] = useState(false);
  const [comment, setComment] = useState("");
  const [correction, setCorrection] = useState("");
  const [learned, setLearned] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const demo = isDemo();

  async function send(rating: "up" | "down", withComment?: string) {
    if (busy || sent) return;
    setError("");
    if (demo) {
      setSent(rating);
      setLearned(false);
      setAskComment(false);
      return;
    }
    setBusy(true);
    try {
      const result = await submitFeedback({
        conversation_id: conversationId ?? null,
        query: question,
        answer,
        rating,
        comment: withComment?.trim() || null,
        correction: correction.trim() || null,
        retrieval_trace: {
          model_route: modelRoute ?? null,
          citations: (citations ?? []).map((c) => ({
            title: c.source_record_title,
            tool: c.source_tool,
            score: c.confidence,
            tier: c.data_tier ?? null,
          })),
        },
      });
      if (!result.recorded) throw new Error("Feedback was not recorded");
      setSent(rating);
      setLearned(!!correction.trim());
      setAskComment(false);
    } catch {
      // Keep the conversation usable, but never claim a failed write persisted.
      setError("Feedback could not be saved. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
        <Check className="size-3" />{" "}
        {demo
          ? "Demo feedback is not saved"
          : learned
          ? "Got it - Sheldon will remember this for your whole team"
          : "Thanks - feedback recorded"}
      </span>
    );
  }

  const btn =
    "inline-flex items-center rounded-full border border-[var(--border)] p-1.5 text-muted-foreground transition-colors hover:border-[var(--border-hover)] hover:text-foreground disabled:opacity-50";

  return (
    <span className="flex max-w-full flex-wrap items-center gap-1.5">
      <button
        type="button"
        aria-label="Good answer"
        className={btn}
        disabled={busy}
        onClick={() => send("up")}
      >
        <ThumbsUp className="size-3" strokeWidth={1.8} />
      </button>
      <button
        type="button"
        aria-label="Bad answer"
        className={cn(btn, askComment && "border-[var(--border-hover)] text-foreground")}
        disabled={busy}
        onClick={() => setAskComment((v) => !v)}
      >
        <ThumbsDown className="size-3" strokeWidth={1.8} />
      </button>
      {askComment && (
        <span className="flex w-full min-w-0 flex-wrap items-center gap-1">
          <input
            className="search-input min-w-0 flex-[1_1_180px]"
            style={{ fontSize: 11, padding: "4px 8px" }}
            aria-label="What was wrong?"
            placeholder="What was wrong? (optional)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") send("down", comment);
            }}
          />
          <input
            className="search-input min-w-0 flex-[1_1_180px]"
            style={{ fontSize: 11, padding: "4px 8px" }}
            aria-label="Correct answer"
            placeholder="What's the right answer? (teaches Sheldon)"
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") send("down", comment);
            }}
          />
          <button
            type="button"
            className={btn}
            style={{ fontSize: 11 }}
            disabled={busy}
            onClick={() => send("down", comment)}
          >
            Send
          </button>
        </span>
      )}
      {error && (
        <span role="alert" className="basis-full text-[11px] text-[var(--red)]">
          {error}
        </span>
      )}
    </span>
  );
}
