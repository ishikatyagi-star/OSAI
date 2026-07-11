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
import { buildOpenUiArtifacts } from "@/lib/openui-artifacts";
import { cn } from "@/lib/utils";
import type { AgentAction, AskResponse } from "@/lib/types";
import { MessageBubble, type AskTurn } from "@/components/ask/message-bubble";
import { getDepartments, type Department } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
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

/** Composer modes. Each mode reframes
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
    placeholder: "Ask anything about your org: projects, owners, decisions, status...",
  },
  {
    id: "search",
    label: "Search",
    icon: Search,
    placeholder: "Search across Notion, Slack, Google Drive, Freshdesk and Zoom...",
  },
  {
    id: "action",
    label: "Take action",
    icon: Zap,
    placeholder: "Tell Sheldon AI to open a ticket, assign an owner, or post a status update...",
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
  gradient: string;
}[] = [
  {
    id: "context",
    icon: Sparkles,
    label: "Ask about context",
    desc: "Get a cited answer pulled from across your tools.",
    example: "Who owns the VPC security setup and is it done?",
    sources: ["Notion", "Slack"],
    gradient: "ask-mode-card--violet",
  },
  {
    id: "summarize",
    icon: Layers,
    label: "Summarize across tools",
    desc: "Roll up threads, tickets and docs into one answer.",
    example: "Summarise open SLA escalations in Freshdesk",
    sources: ["Freshdesk", "Zoom"],
    gradient: "ask-mode-card--magenta",
  },
  {
    id: "action",
    icon: Zap,
    label: "Take an action",
    desc: "Open tickets, assign owners or post updates, with approval.",
    example: "Open a Freshdesk ticket for the Redis connection pool issue",
    sources: ["Freshdesk"],
    gradient: "ask-mode-card--orange",
  },
];

export default function AskPage() {
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<ComposerMode>("ask");
  const [pending, setPending] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [busyActionId, setBusyActionId] = useState<string | null>(null);
  // Department scope: restrict retrieval to one department's documents.
  const [departments, setDepartments] = useState<Department[]>([]);
  const [departmentId, setDepartmentId] = useState<string>("");

  useEffect(() => {
    getDepartments().then(setDepartments).catch(() => setDepartments([]));
  }, []);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Focus the composer on mount and whenever a response finishes, so the user
  // can start (or keep) typing without clicking into the field.
  useEffect(() => {
    if (!pending) inputRef.current?.focus({ preventScroll: true });
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
        question: q,
        conversationId: res.conversation_id ?? conversationId,
        citations: res.citations,
        actions: res.actions_taken,
        enoughContext: res.enough_context,
        modelRoute: res.model_route,
        latencyMs: res.latency_ms,
        artifacts: buildOpenUiArtifacts(res),
      });

      try {
        const res = isDemo()
          ? getDemoAnswer(q)
          : await askOsai(q, { conversationId, history, departmentId: departmentId || null });
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
                "I couldn't reach the Sheldon AI backend just now. Check your connection and try again.",
            },
          ]);
        }
      } finally {
        setPending(false);
      }
    },
    [pending, turns, conversationId, departmentId]
  );

  // Deep links (e.g. the Automations page's "Create with Sheldon AI") seed the
  // composer via ?q=…; prefill only, so the user can review before sending.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) setInput(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      if (isDemo()) {
        patchAction(turnId, action.id, {
          status: "executed",
          requires_confirmation: false,
          external_url:
            action.tool === "freshdesk"
              ? "https://freshdesk.com/tickets/205"
              : `https://example.com/${action.tool}/created`,
          error: null,
        });
        setBusyActionId(null);
        return;
      }
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
        // Real workspace: never claim success or fabricate a URL. Surface the
        // failure honestly and let the user retry.
        patchAction(turnId, action.id, {
          status: "failed",
          requires_confirmation: false,
          external_url: null,
          error: "Couldn't complete this action. Please try again.",
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
    <div className="ask-canvas flex min-h-[calc(100vh-128px)] flex-col">
      {/* Header */}
      <div className="page-header shrink-0">
        <div className="page-header-left">
          <h1>Ask Sheldon AI</h1>
          <p>
            Ask anything about your org and get a cited answer, or have Sheldon AI open
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
        /* EMPTY STATE */
        <div className="ask-scroll flex-1">
          <div className="flex min-h-full items-center justify-center px-4 py-8">
            <div className="ask-column flex w-full max-w-[760px] flex-col gap-8 text-left">
              {/* Heading */}
              <div className="flex flex-col gap-4">
                <h2 className="ask-title">What would you like to know?</h2>
              </div>

              {/* HERO composer */}
              {departments.length > 0 && (
                <div className="mb-2 flex items-center justify-center gap-2 text-xs text-muted-foreground">
                  <label className="inline-flex items-center gap-2">
                    Scope
                    <select
                      aria-label="Department scope"
                      value={departmentId}
                      onChange={(e) => setDepartmentId(e.target.value)}
                      style={{
                        background: "var(--bg-surface)",
                        color: "inherit",
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                        padding: "4px 8px",
                      }}
                    >
                      <option value="">Whole workspace</option>
                      {departments.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              )}
              <form onSubmit={handleSubmit} className="w-full">
                <div className="ask-composer ask-composer-hero">
                  <div className="flex items-center gap-3 px-4 py-3">
                    <Plus className="size-5 shrink-0 text-[var(--text-secondary)]" />
                    <Textarea
                      ref={inputRef}
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={handleKeyDown}
                      rows={1}
                      placeholder={activeMode.placeholder}
                      aria-label="Ask Sheldon AI prompt"
                      className="max-h-44 min-h-[44px] flex-1 resize-none self-center border-0 bg-transparent px-1 py-1 text-base shadow-none outline-none focus-visible:ring-0 placeholder:text-[var(--text-muted)]"
                      autoFocus
                    />
                    <Button
                      type="submit"
                      size="icon"
                      className="ask-send-button size-11 shrink-0 self-center rounded-full bg-[var(--text-primary)] text-white hover:bg-[var(--primary-active,#292524)]"
                      disabled={pending || !input.trim()}
                      aria-label="Send"
                      title="Send"
                    >
                      {pending ? (
                        <Loader2 className="size-5 animate-spin" />
                      ) : (
                        <ArrowUp className="size-5" />
                      )}
                    </Button>
                  </div>
                </div>
                {/* Mode pills below the input bar */}
                <Tabs
                  value={mode}
                  onValueChange={(value) => {
                    setMode(value as ComposerMode);
                    inputRef.current?.focus({ preventScroll: true });
                  }}
                >
                  <TabsList
                    className="ask-composer-modes"
                    aria-label="Choose how Sheldon AI should help"
                  >
                    {COMPOSER_MODES.map((m) => {
                      const Icon = m.icon;
                      return (
                        <TabsTrigger
                          key={m.id}
                          value={m.id}
                          className="ask-mode-pill"
                        >
                          <Icon className="size-3.5" />
                          {m.label}
                        </TabsTrigger>
                      );
                    })}
                  </TabsList>
                </Tabs>
              </form>

              {/* Response expectations */}
              <div className="flex flex-wrap items-center gap-x-6 gap-y-1.5">
                <span className="ask-expectation">
                  <ShieldCheck className="size-3.5" />
                  Answers include sources and confidence
                </span>
                <span className="ask-expectation">
                  <Zap className="size-3.5" />
                  Actions run only after you approve
                </span>
              </div>

              {/* Recommended workflows */}
              <div className="flex flex-col gap-3">
                <span className="ask-section-label">Recommended workflows</span>
                <div className="grid gap-2">
                  {ASK_MODES.map((m) => {
                    const Icon = m.icon;
                    return (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => send(m.example)}
                        className={cn("ask-mode-card", m.gradient)}
                      >
                        <span className="ask-mode-card-icon">
                          <Icon className="size-4" />
                        </span>
                        <span className="ask-mode-card-title">{m.label}</span>
                        <span className="ask-mode-card-desc">{m.desc}</span>
                        <span className="ask-example">“{m.example}”</span>
                        <span className="ask-source-badge">{m.sources.join(" + ")}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Disclaimer */}
              <p className="ask-disclaimer">
                Sheldon AI can make mistakes. Actions that change your tools always
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
            className="ask-scroll max-h-[calc(100vh-260px)] min-h-[320px] overflow-y-auto"
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
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-extrabold text-primary-foreground">
                    O
                  </div>
                  <div className="flex items-center gap-2 rounded-xl rounded-tl-sm border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-3 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin text-primary" />
                    Searching across your connected knowledge base...
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Composer pinned to the bottom of the thread */}
          <form onSubmit={handleSubmit} className="shrink-0 pt-4">
            <div className="mx-auto w-full max-w-3xl">
              <div className="ask-composer flex items-center gap-2 px-4 py-3">
                <Textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  rows={1}
                  placeholder="Ask a follow-up..."
                  aria-label="Ask Sheldon AI follow-up prompt"
                  className="max-h-40 min-h-[40px] flex-1 resize-none self-center border-0 bg-transparent px-1 py-1.5 text-sm shadow-none outline-none focus-visible:ring-0 placeholder:text-[var(--text-muted)]"
                  autoFocus
                />
                <Button
                  type="submit"
                  size="icon"
                  className="ask-send-button size-11 shrink-0 self-center rounded-full bg-[var(--text-primary)] text-white hover:bg-[var(--primary-active,#292524)]"
                  disabled={pending || !input.trim()}
                  aria-label="Send"
                  title="Send"
                >
                  {pending ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <ArrowUp className="size-4" />
                  )}
                </Button>
              </div>
              <p className="ask-disclaimer mt-2 text-center">
                Sheldon AI can make mistakes. Actions that change your tools always
                require approval.
              </p>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
