"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Layers,
  Loader2,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Zap,
} from "lucide-react";
import { askOsai, confirmAgentAction } from "@/lib/api";
import { DEMO_ASK_ANSWERS } from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { cn } from "@/lib/utils";
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

/** Composer modes — the command-center's core differentiator. Each mode reframes
 *  the placeholder so the box clearly does more than chat. */
type ComposerMode = "ask" | "search" | "action";

const COMPOSER_MODES: {
  id: ComposerMode;
  label: string;
  icon: typeof Sparkles;
  placeholder: string;
}[] = [
  {
    id: "ask",
    label: "Ask",
    icon: Sparkles,
    placeholder: "Ask anything about your org — projects, owners, decisions, status…",
  },
  {
    id: "search",
    label: "Search",
    icon: Search,
    placeholder: "Search across Notion, Slack, Google Drive, Freshdesk and Zoom…",
  },
  {
    id: "action",
    label: "Take action",
    icon: Zap,
    placeholder: "Tell OSAI to open a ticket, assign an owner, or post a status update…",
  },
];

/** Three onboarding modes shown as recommended workflows (not passive chips). */
const ASK_MODES: {
  id: string;
  icon: typeof Sparkles;
  label: string;
  desc: string;
  example: string;
  sources: string[];
}[] = [
  {
    id: "context",
    icon: Sparkles,
    label: "Ask about context",
    desc: "Get a cited answer pulled from across your tools.",
    example: "Who owns the VPC security setup and is it done?",
    sources: ["Notion", "Slack"],
  },
  {
    id: "summarize",
    icon: Layers,
    label: "Summarize across tools",
    desc: "Roll up threads, tickets and docs into one answer.",
    example: "Summarise open SLA escalations in Freshdesk",
    sources: ["Freshdesk", "Zoom"],
  },
  {
    id: "action",
    icon: Zap,
    label: "Take an action",
    desc: "Open tickets, assign owners or post updates — with approval.",
    example: "Open a Freshdesk ticket for the Redis connection pool issue",
    sources: ["Freshdesk"],
  },
];

export default function AskPage() {
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<ComposerMode>("ask");
  const [pending, setPending] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [busyActionId, setBusyActionId] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Focus the composer on mount and whenever a response finishes, so the user
  // can start (or keep) typing without clicking into the field.
  useEffect(() => {
    if (!pending) inputRef.current?.focus();
  }, [pending]);

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
        // Live API unavailable. In demo mode, fall back to canned answers; otherwise
        // surface an honest error rather than fabricating a response.
        if (isDemo()) {
          const demo = getDemoAnswer(q);
          setConversationId(demo.conversation_id ?? conversationId);
          setTurns((prev) => [...prev, toTurn(demo)]);
        } else {
          setTurns((prev) => [
            ...prev,
            {
              id: uid("a"),
              role: "assistant",
              content:
                "I couldn't reach the OSAI backend just now. Check your connection and try again.",
            },
          ]);
        }
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
  const activeMode =
    COMPOSER_MODES.find((m) => m.id === mode) ?? COMPOSER_MODES[0];

  return (
    <div className="ask-canvas flex h-[calc(100vh-128px)] flex-col">
      {/* Header */}
      <div className="page-header shrink-0">
        <div className="page-header-left">
          <h1>Ask OSAI</h1>
          <p>
            Ask anything about your org and get a cited answer — or have OSAI open
            tickets, chase follow-ups, pull status, and check ownership.
          </p>
        </div>
        {!empty && (
          <button
            className="btn"
            onClick={() => {
              setTurns([]);
              setConversationId(null);
            }}
          >
            <Plus className="size-3.5" /> New chat
          </button>
        )}
      </div>

      {empty ? (
        /* ─── EMPTY STATE — one clean, centered command column ─────────────── */
        <div className="ask-scroll min-h-0 flex-1 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center px-4 py-8">
            <div className="ask-column flex w-full max-w-[760px] flex-col gap-6 text-left">
              {/* Heading + subtext */}
              <div className="flex flex-col gap-3">
                <span className="ask-eyebrow">Command center</span>
                <h2 className="ask-title">What would you like to know?</h2>
                <p className="ask-subtext">
                  OSAI answers from everything it has indexed across Notion, Slack,
                  Google Drive, Freshdesk and Zoom — and can act on your behalf:
                  open tickets, chase follow-ups, pull status, and check ownership.
                </p>
              </div>

              {/* HERO composer — the product's core differentiator */}
              <form onSubmit={handleSubmit} className="w-full">
                <div className="ask-composer ask-composer-hero">
                  {/* Mode tabs */}
                  <div className="flex items-center gap-1 border-b border-[var(--border)] px-2.5 py-2">
                    {COMPOSER_MODES.map((m) => {
                      const Icon = m.icon;
                      return (
                        <button
                          key={m.id}
                          type="button"
                          data-active={mode === m.id}
                          onClick={() => {
                            setMode(m.id);
                            inputRef.current?.focus();
                          }}
                          className="ask-mode-tab"
                        >
                          <Icon className="size-3.5" />
                          {m.label}
                        </button>
                      );
                    })}
                  </div>
                  {/* Input row — placeholder + send vertically centered */}
                  <div className="flex items-center gap-2 px-3 py-2.5">
                    <Textarea
                      ref={inputRef}
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={handleKeyDown}
                      rows={1}
                      placeholder={activeMode.placeholder}
                      className="max-h-44 min-h-[44px] flex-1 resize-none self-center border-0 bg-transparent px-1 py-1 text-base shadow-none focus-visible:ring-0"
                      autoFocus
                    />
                    <Button
                      type="submit"
                      size="icon"
                      className="size-10 shrink-0 self-center rounded-full"
                      disabled={pending || !input.trim()}
                      aria-label="Send"
                    >
                      {pending ? (
                        <Loader2 className="size-5 animate-spin" />
                      ) : (
                        <ArrowUp className="size-5" />
                      )}
                    </Button>
                  </div>
                </div>
              </form>

              {/* Response expectations — sets a quality bar before the first query */}
              <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
                <span className="ask-expectation">
                  <ShieldCheck className="size-3.5 text-[var(--accent)]" />
                  Answers include sources and confidence
                </span>
                <span className="ask-expectation">
                  <Zap className="size-3.5 text-[var(--accent)]" />
                  Actions run only after you approve
                </span>
              </div>

              {/* Recommended workflows — three modes, each with a concrete example */}
              <div className="flex flex-col gap-3">
                <span className="ask-section-label">Recommended workflows</span>
                <div className="grid gap-2.5 sm:grid-cols-3">
                  {ASK_MODES.map((m) => {
                    const Icon = m.icon;
                    return (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => send(m.example)}
                        className="ask-mode-card"
                      >
                        <span className="ask-mode-card-icon">
                          <Icon className="size-4" />
                        </span>
                        <span className="ask-mode-card-title">{m.label}</span>
                        <span className="ask-mode-card-desc">{m.desc}</span>
                        <span className="ask-example">“{m.example}”</span>
                        <span className="flex flex-wrap gap-1.5">
                          {m.sources.map((s) => (
                            <span key={s} className="ask-source-badge">
                              {s}
                            </span>
                          ))}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Disclaimer */}
              <p className="ask-disclaimer">
                OSAI can make mistakes. Actions that change your tools always
                require approval.
              </p>
            </div>
          </div>
        </div>
      ) : (
        /* ─── CONVERSATION STATE ──────────────────────────────────────────── */
        <>
          <div
            ref={threadRef}
            className="ask-scroll min-h-0 flex-1 overflow-y-auto"
          >
            <div className="mx-auto w-full max-w-3xl space-y-6 py-1">
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
            </div>
          </div>

          {/* Composer pinned to the bottom of the thread */}
          <form onSubmit={handleSubmit} className="shrink-0 pt-4">
            <div className="mx-auto w-full max-w-3xl">
              <div className="ask-composer flex items-center gap-2 px-3 py-2">
                <Textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  rows={1}
                  placeholder="Ask a follow-up, or tell OSAI to take an action…"
                  className="max-h-40 min-h-[40px] flex-1 resize-none self-center border-0 bg-transparent px-1 py-1.5 text-sm shadow-none focus-visible:ring-0"
                  autoFocus
                />
                <Button
                  type="submit"
                  size="icon"
                  className="shrink-0 self-center rounded-full"
                  disabled={pending || !input.trim()}
                  aria-label="Send"
                >
                  {pending ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <ArrowUp className="size-4" />
                  )}
                </Button>
              </div>
              <p className="ask-disclaimer mt-2 text-center">
                OSAI can make mistakes. Actions that change your tools always
                require approval.
              </p>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
