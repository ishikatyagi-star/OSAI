"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Plus, Send, Sparkles } from "lucide-react";
import { askOsai, confirmAgentAction } from "@/lib/api";
import { DEMO_ASK_ANSWERS, DEMO_ASK_SUGGESTIONS } from "@/lib/demo-data";
import type { AgentAction, AskResponse } from "@/lib/types";
import { MessageBubble, type AskTurn } from "@/components/ask/message-bubble";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

function normaliseKey(q: string) {
  return q.toLowerCase().replace(/[^a-z0-9 ]/g, "").trim();
}

/** Pick the closest demo answer when the live API is unavailable. */
function getDemoAnswer(question: string): AskResponse {
  const key = normaliseKey(question);
  for (const [k, v] of Object.entries(DEMO_ASK_ANSWERS)) {
    if (k === "default") continue;
    if (key.includes(k) || k.includes(key)) return v;
  }
  return DEMO_ASK_ANSWERS.default;
}

function uid(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 9)}`;
}

export default function AskPage() {
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [busyActionId, setBusyActionId] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      const el = threadRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }, []);

  useEffect(scrollToBottom, [turns, pending, scrollToBottom]);

  const send = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || pending) return;

      const userTurn: AskTurn = { id: uid("u"), role: "user", content: q };
      const history = turns.map((t) => ({ role: t.role, content: t.content }));
      setTurns((prev) => [...prev, userTurn]);
      setInput("");
      setPending(true);

      const toTurn = (res: AskResponse): AskTurn => ({
        id: uid("a"),
        role: "assistant",
        content: res.answer,
        citations: res.citations,
        actions: res.actions_taken,
        enoughContext: res.enough_context,
        modelRoute: res.model_route,
        latencyMs: res.latency_ms,
      });

      try {
        const res = await askOsai(q, { conversationId, history });
        setConversationId(res.conversation_id ?? conversationId);
        setTurns((prev) => [...prev, toTurn(res)]);
      } catch {
        // Live API unavailable — fall back to demo answers (same pattern as Search).
        const demo = getDemoAnswer(q);
        setConversationId(demo.conversation_id ?? conversationId);
        setTurns((prev) => [...prev, toTurn(demo)]);
      } finally {
        setPending(false);
      }
    },
    [pending, turns, conversationId]
  );

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    send(input);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  }

  /** Update one action inside one assistant turn. */
  const patchAction = useCallback(
    (turnId: string, actionId: string, patch: Partial<AgentAction>) => {
      setTurns((prev) =>
        prev.map((t) =>
          t.id !== turnId
            ? t
            : {
                ...t,
                actions: t.actions?.map((a) =>
                  a.id === actionId ? { ...a, ...patch } : a
                ),
              }
        )
      );
    },
    []
  );

  const handleApprove = useCallback(
    async (turnId: string, action: AgentAction) => {
      setBusyActionId(action.id);
      try {
        const res = await confirmAgentAction(
          action.id,
          conversationId ?? "conv-demo"
        );
        patchAction(turnId, action.id, {
          status: res.status,
          external_url: res.external_url,
          error: res.error,
          requires_confirmation: false,
        });
      } catch {
        // Demo fallback — simulate a successful execution.
        patchAction(turnId, action.id, {
          status: "executed",
          requires_confirmation: false,
          external_url:
            action.tool === "freshdesk"
              ? "https://freshdesk.com/tickets/205"
              : `https://example.com/${action.tool}/created`,
          error: null,
        });
      } finally {
        setBusyActionId(null);
      }
    },
    [conversationId, patchAction]
  );

  const handleDismiss = useCallback(
    (turnId: string, action: AgentAction) => {
      patchAction(turnId, action.id, {
        status: "skipped",
        requires_confirmation: false,
      });
    },
    [patchAction]
  );

  const empty = turns.length === 0;

  return (
    <div className="flex h-[calc(100vh-128px)] flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between pb-4">
        <div>
          <h1 className="flex items-center gap-2">
            <Sparkles className="size-5 text-primary" />
            Ask OSAI
          </h1>
          <p className="page-subtitle" style={{ marginBottom: 0 }}>
            Ask anything about your org — get a cited answer and let OSAI take action in your tools.
          </p>
        </div>
        {!empty && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setTurns([]);
              setConversationId(null);
            }}
          >
            <Plus className="size-3.5" /> New chat
          </Button>
        )}
      </div>

      {/* Thread */}
      <div
        ref={threadRef}
        className="min-h-0 flex-1 space-y-6 overflow-y-auto pr-1"
      >
        {empty ? (
          <div className="mx-auto flex max-w-2xl flex-col items-center justify-center gap-6 py-12 text-center">
            <div className="flex size-14 items-center justify-center rounded-2xl bg-primary/15 text-2xl font-extrabold text-primary">
              O
            </div>
            <div className="space-y-1.5">
              <h2 className="text-lg">What would you like to know?</h2>
              <p className="max-w-md text-sm text-muted-foreground">
                OSAI answers from everything it has indexed across Notion, Slack, Google
                Drive, Freshdesk and Zoom — and can take actions on your behalf.
              </p>
            </div>
            <div className="grid w-full max-w-xl gap-2 sm:grid-cols-2">
              {DEMO_ASK_SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  className="rounded-lg border border-border bg-card px-4 py-3 text-left text-sm text-foreground/90 transition-colors hover:border-input hover:bg-accent"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {turns.map((t) => (
              <MessageBubble
                key={t.id}
                turn={t}
                busyActionId={busyActionId}
                onApprove={handleApprove}
                onDismiss={handleDismiss}
              />
            ))}
            {pending && (
              <div className="flex gap-3">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-sm font-extrabold text-primary-foreground">
                  O
                </div>
                <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin text-primary" />
                  Searching across your connected knowledge base…
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Composer */}
      <form onSubmit={handleSubmit} className="shrink-0 pt-4">
        <div className="flex items-end gap-2 rounded-xl border border-border bg-card p-2 focus-within:border-input">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder="Ask OSAI anything, or tell it to take an action…"
            className="max-h-40 min-h-[40px] flex-1 border-0 bg-transparent shadow-none focus-visible:ring-0"
            autoFocus
          />
          <Button type="submit" size="icon" disabled={pending || !input.trim()}>
            {pending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Send className="size-4" />
            )}
          </Button>
        </div>
        <p className="mt-1.5 text-center text-[11px] text-muted-foreground">
          OSAI can make mistakes. Actions that change your tools always require approval.
        </p>
      </form>
    </div>
  );
}
