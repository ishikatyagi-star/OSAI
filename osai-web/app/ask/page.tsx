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
import {
  ApiError,
  askOsai,
  confirmAgentAction,
  dismissAgentAction,
  searchOsai,
} from "@/lib/api";
import {
  DEMO_ASK_ANSWERS,
  DEMO_DEPARTMENTS,
  DEMO_SEARCH_ANSWERS,
} from "@/lib/demo-data";
import { isDemo } from "@/lib/demo";
import { buildOpenUiArtifacts } from "@/lib/openui-artifacts";
import { cn } from "@/lib/utils";
import type { AgentAction, AskResponse, SearchResponse } from "@/lib/types";
import { MessageBubble, type AskTurn } from "@/components/ask/message-bubble";
import { ComposerAttach } from "@/components/ask/composer-attach";
import {
  getDepartments,
  getNotifications,
  getThread,
  listThreads,
  markNotificationRead,
  patchThread,
  type AppNotification,
  type Department,
  type ThreadSummary,
  type ThreadTurnRow,
} from "@/lib/api";
import type { UploadedFile } from "@/components/ask/file-card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { SheldonMascot } from "@/components/sheldon-mascot";
import { announceNotificationsChanged } from "@/lib/notification-events";

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

function getDemoSearchAnswer(question: string): SearchResponse {
  const key = normaliseKey(question);
  for (const [k, v] of Object.entries(DEMO_SEARCH_ANSWERS)) {
    if (k === "default") continue;
    if (key.includes(k) || k.includes(key)) return v;
  }
  return DEMO_SEARCH_ANSWERS.default;
}

function uid(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 9)}`;
}

function shouldRetryAsk(error: unknown) {
  return (
    (error instanceof Error && error.name === "AbortError") ||
    (error instanceof ApiError && error.status === 503)
  );
}

function hydrateThreadTurns(rows: ThreadTurnRow[]): AskTurn[] {
  let question: string | undefined;
  return rows.map((turn) => {
    if (turn.role === "user") {
      question = turn.content;
      return { id: turn.id, role: turn.role, content: turn.content };
    }
    const stored = turn.payload?.ask_response;
    const response =
      stored && typeof stored === "object"
        ? (stored as unknown as AskResponse)
        : undefined;
    return {
      id: turn.id,
      role: turn.role,
      content: turn.content,
      question,
      conversationId: response?.conversation_id,
      citations:
        response?.citations ??
        ((turn.payload?.citations as AskTurn["citations"]) ?? undefined),
      actions: response?.actions_taken,
      enoughContext: response?.enough_context,
      modelRoute: response?.model_route,
      latencyMs: response?.latency_ms,
      artifacts: response ? buildOpenUiArtifacts(response) : undefined,
    };
  });
}

/** Composer modes. Each mode reframes
 *  the placeholder so the box clearly does more than chat. */
type ComposerMode = "ask" | "search" | "action";
const MAX_ASK_QUESTION_CHARS = 40_000;
const MAX_SEARCH_QUERY_CHARS = 4_000;
const MAX_HISTORY_TURNS = 10;
const MAX_HISTORY_CONTENT_CHARS = 4_000;

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
    placeholder: "Ask anything about your org...",
  },
  {
    id: "search",
    label: "Search",
    icon: Search,
    placeholder: "Search connected tools...",
  },
  {
    id: "action",
    label: "Take action",
    icon: Zap,
    placeholder: "Describe an action...",
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
    sources: ["Freshdesk", "Google Drive"],
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
  const demo = isDemo();
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<ComposerMode>("ask");
  const inputMaxLength =
    mode === "search" ? MAX_SEARCH_QUERY_CHARS : MAX_ASK_QUESTION_CHARS;
  const [pending, setPending] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [busyActions, setBusyActions] = useState<
    Record<string, "approve" | "dismiss">
  >({});
  // Persisted thread backing this conversation (multiplayer surface).
  const [threadId, setThreadId] = useState<string | null>(null);
  const [threadShared, setThreadShared] = useState(false);
  const [threadList, setThreadList] = useState<ThreadSummary[]>([]);
  const [threadsOpen, setThreadsOpen] = useState(false);
  const [threadListLoading, setThreadListLoading] = useState(false);
  const [threadListError, setThreadListError] = useState("");
  const [threadActionError, setThreadActionError] = useState("");
  const [openingThreadId, setOpeningThreadId] = useState<string | null>(null);
  const [sharingThread, setSharingThread] = useState(false);
  // Department scope: restrict retrieval to one department's documents.
  const [departments, setDepartments] = useState<Department[]>([]);
  const [departmentId, setDepartmentId] = useState<string>("");

  useEffect(() => {
    if (isDemo()) {
      setDepartments(DEMO_DEPARTMENTS);
      return;
    }
    getDepartments().then(setDepartments).catch(() => setDepartments([]));
  }, []);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const threadsTriggerRef = useRef<HTMLButtonElement>(null);

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

      const requestId = crypto.randomUUID();
      const userTurn: AskTurn = { id: requestId, role: "user", content: q };
      const history = turns.slice(-MAX_HISTORY_TURNS).map((t) => ({
        role: t.role,
        content: t.content.slice(0, MAX_HISTORY_CONTENT_CHARS),
      }));
      setTurns((prev) => [...prev, userTurn]);
      setInput("");
      setPending(true);

      const toTurn = (res: AskResponse | SearchResponse): AskTurn => {
        const askResponse = "conversation_id" in res ? res : null;
        return {
          id: uid("a"),
          role: "assistant",
          content: res.answer,
          question: q,
          conversationId: askResponse?.conversation_id ?? conversationId,
          citations: res.citations,
          actions: askResponse?.actions_taken,
          enoughContext: res.enough_context,
          modelRoute: askResponse?.model_route,
          latencyMs: askResponse?.latency_ms,
          artifacts: askResponse ? buildOpenUiArtifacts(askResponse) : undefined,
        };
      };

      try {
        // The demo workspace answers with the live LLM over the seeded demo-org
        // data (X-Org-Id: demo-org travels in the request), so demo questions get
        // real, varied answers instead of a single canned reply. If the backend
        // is slow or unreachable, the catch below falls back to the canned demo
        // answers so the demo never hangs or errors.
        if (mode === "search") {
          const res = await searchOsai(q, { departmentId: departmentId || null });
          setTurns((prev) => [...prev, toTurn(res)]);
        } else {
          const askOptions = {
            conversationId,
            history,
            departmentId: departmentId || null,
            intent: mode === "action" ? ("action" as const) : ("ask" as const),
            // The signed-in server owns thread creation plus both turn writes.
            threadId: isDemo() ? null : threadId,
            requestId: isDemo() ? null : requestId,
          };
          let res: AskResponse;
          try {
            res = await askOsai(q, askOptions);
          } catch (error) {
            if (isDemo() || !shouldRetryAsk(error)) throw error;
            // A timed-out first request may still be finishing server-side. The
            // same key waits for/replays it instead of running the model twice.
            res = await askOsai(q, askOptions);
          }
          setConversationId(res.conversation_id ?? conversationId);
          if (res.thread_id) {
            if (res.thread_id !== threadId) setThreadShared(false);
            setThreadId(res.thread_id);
          }
          setTurns((prev) => [...prev, toTurn(res)]);
        }
      } catch (error) {
        // Live API unavailable. In demo mode, fall back to canned answers; otherwise
        // surface an honest error rather than fabricating a response.
        if (isDemo()) {
          if (mode === "search") {
            setTurns((prev) => [...prev, toTurn(getDemoSearchAnswer(q))]);
          } else {
            const fallback = getDemoAnswer(q);
            setConversationId(fallback.conversation_id ?? conversationId);
            setTurns((prev) => [...prev, toTurn(fallback)]);
          }
        } else {
          const invalidSearchQuery =
            mode === "search" && error instanceof ApiError && error.status === 422;
          const persistenceFailure =
            mode !== "search" && error instanceof ApiError && error.status >= 409;
          setTurns((prev) => [
            ...prev,
            {
              id: uid("a"),
              role: "assistant",
              content: invalidSearchQuery
                ? "Search queries must be between 1 and 4,000 characters."
                : persistenceFailure
                  ? "I couldn't safely save this answer. Refresh the thread and try again."
                  : "I couldn't reach the Sheldon backend just now. Check your connection and try again.",
            },
          ]);
        }
      } finally {
        setPending(false);
      }
    },
    [pending, turns, conversationId, departmentId, threadId, mode]
  );

  // Deep links (e.g. the Automations page's "Create with Sheldon") seed the
  // composer via ?q=…; prefill only, so the user can review before sending.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("q");
    if (q) setInput(q);
    const requestedMode = params.get("mode");
    if (requestedMode && COMPOSER_MODES.some((item) => item.id === requestedMode)) {
      setMode(requestedMode as ComposerMode);
    }
    const tid = params.get("thread");
    if (tid && !isDemo()) void openThread(tid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openThread(tid: string) {
    if (pending || openingThreadId) return false;
    setOpeningThreadId(tid);
    setThreadActionError("");
    try {
      const t = await getThread(tid, true);
      if (!t) throw new Error("Thread not found");
      setThreadId(t.id);
      setThreadShared(t.shared);
      setConversationId(null);
      setMode("ask");
      setThreadsOpen(false);
      setTurns(hydrateThreadTurns(t.turns));
      return true;
    } catch {
      setThreadActionError("That thread could not be loaded. Check your connection and try again.");
      return false;
    } finally {
      setOpeningThreadId(null);
    }
  }

  async function loadThreads() {
    setThreadListLoading(true);
    setThreadListError("");
    if (isDemo()) {
      setThreadList([]);
      setThreadListLoading(false);
      return;
    }
    try {
      setThreadList(await listThreads(true));
    } catch {
      setThreadListError("Saved threads could not be loaded. Check your connection and retry.");
    } finally {
      setThreadListLoading(false);
    }
  }

  async function toggleThreads() {
    if (pending) return;
    const next = !threadsOpen;
    setThreadsOpen(next);
    if (!next) return;
    await loadThreads();
  }

  async function toggleShared() {
    if (!threadId || sharingThread) return;
    setSharingThread(true);
    setThreadActionError("");
    try {
      const t = await patchThread(threadId, { shared: !threadShared });
      setThreadShared(t.shared);
    } catch {
      setThreadActionError("Thread sharing could not be updated. Only the creator can change access.");
    } finally {
      setSharingThread(false);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    send(input);
  }

  // A successful upload lands in the thread as file cards (with a ⋯ menu to
  // manage access), so the file is immediately askable in context.
  const handleUploaded = useCallback(
    (files: UploadedFile[], skipped: { filename: string; reason: string }[]) => {
      const notes = skipped.map((s) => `${s.filename}: ${s.reason}`);
      const content =
        files.length > 0
          ? `Added to your knowledge base - private to you until you share ${
              files.length > 1 ? "them" : "it"
            } (⋯ → Manage access).${notes.length ? ` ${notes.join(" ")}` : ""}`
          : notes.join(" ");
      setTurns((prev) => [
        ...prev,
        { id: uid("a"), role: "assistant", content, files },
      ]);
    },
    []
  );

  const handleUploadError = useCallback((message: string) => {
    setTurns((prev) => [...prev, { id: uid("a"), role: "assistant", content: message }]);
  }, []);

  // "X shared a file with you" - unread share notifications, dismissible.
  const [shareNotices, setShareNotices] = useState<AppNotification[]>([]);
  useEffect(() => {
    if (isDemo()) {
      setShareNotices([]);
      return;
    }
    getNotifications()
      .then((all) =>
        setShareNotices(
          all.filter((n) => n.type === "document.shared" || n.type === "thread.mention")
        )
      )
      .catch(() => setShareNotices([]));
  }, []);
  const dismissNotice = useCallback(async (id: string) => {
    try {
      await markNotificationRead(id);
      setShareNotices((prev) => prev.filter((n) => n.id !== id));
      announceNotificationsChanged();
      return true;
    } catch {
      setThreadActionError("That notification could not be marked as read. Please retry.");
      return false;
    }
  }, []);

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

  const setActionBusy = useCallback(
    (actionId: string, operation: "approve" | "dismiss" | null) => {
      setBusyActions((previous) => {
        const next = { ...previous };
        if (operation) next[actionId] = operation;
        else delete next[actionId];
        return next;
      });
    },
    []
  );

  const handleApprove = useCallback(
    async (turnId: string, action: AgentAction) => {
      setActionBusy(action.id, "approve");
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
        setActionBusy(action.id, null);
        return;
      }
      try {
        const res = await confirmAgentAction(
          action.id,
          conversationId ?? "conv-demo"
        );
        const retryable = res.error === "approval_unavailable";
        patchAction(turnId, action.id, {
          status: retryable ? "proposed" : res.status,
          external_url: retryable ? null : res.external_url,
          error: res.error ? res.message : null,
          requires_confirmation: retryable,
        });
      } catch {
        // A lost response can hide a completed provider side effect. Keep this
        // terminal so the UI never invites a duplicate confirmation.
        patchAction(turnId, action.id, {
          status: "failed",
          requires_confirmation: false,
          external_url: null,
          error: "The result of this action is unknown. Check the destination before proposing it again.",
        });
      } finally {
        setActionBusy(action.id, null);
      }
    },
    [conversationId, patchAction, setActionBusy]
  );

  const handleDismiss = useCallback(
    async (turnId: string, action: AgentAction) => {
      if (isDemo()) {
        patchAction(turnId, action.id, {
          status: "skipped",
          requires_confirmation: false,
          error: null,
        });
        return;
      }
      setActionBusy(action.id, "dismiss");
      try {
        const res = await dismissAgentAction(
          action.id,
          conversationId ?? "conv-demo"
        );
        const retryable = res.error === "approval_unavailable";
        patchAction(turnId, action.id, {
          status: retryable ? "proposed" : res.status,
          requires_confirmation: retryable,
          external_url: null,
          error: res.error ? res.message : null,
        });
      } catch {
        patchAction(turnId, action.id, {
          status: "proposed",
          requires_confirmation: true,
          external_url: null,
          error: "Couldn't dismiss this action. Please try again.",
        });
      } finally {
        setActionBusy(action.id, null);
      }
    },
    [conversationId, patchAction, setActionBusy]
  );

  const empty = turns.length === 0;
  const activeMode =
    COMPOSER_MODES.find((m) => m.id === mode) ?? COMPOSER_MODES[0];

  return (
    <div className="ask-canvas flex min-h-[calc(100vh-128px)] flex-col">
      {/* Header */}
      <div className="page-header ask-page-header shrink-0" data-conversation={!empty}>
        <div className="page-header-left">
          <h1>Ask Sheldon</h1>
          <p>
            Ask anything about your org and get a cited answer, or have Sheldon open
            tickets, chase follow-ups, pull status, and check ownership.
          </p>
        </div>
        <button
          ref={threadsTriggerRef}
          className="btn"
          aria-label="Threads"
          aria-expanded={threadsOpen}
          aria-controls="ask-thread-list"
          onClick={toggleThreads}
          disabled={pending}
        >
          Threads
        </button>
        {!empty && threadId && (
          <button
            className="btn"
            aria-label={threadShared ? "Make thread private" : "Share thread with your org"}
            onClick={toggleShared}
            disabled={sharingThread}
          >
            {sharingThread ? "Updating…" : threadShared ? "Shared ✓" : "Share"}
          </button>
        )}
        {!empty && (
          <button
            className="btn"
            aria-label="New chat"
            onClick={() => {
              setTurns([]);
              setConversationId(null);
              setThreadId(null);
              setThreadShared(false);
            }}
            disabled={pending}
          >
            <Plus className="size-3.5" />
            <span className="ask-new-chat-wide">New chat</span>
            <span className="ask-new-chat-compact" aria-hidden>New</span>
          </button>
        )}
      </div>

      {threadActionError && (
        <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-2">
          <div className="card error-text" role="alert" style={{ padding: "10px 14px" }}>
            {threadActionError}
          </div>
        </div>
      )}

      {/* Threads live in a right-hand slide-in drawer (Claude-style) so opening
          the list never pushes the conversation down or eats vertical space. */}
      <Dialog open={threadsOpen} onOpenChange={setThreadsOpen}>
        <DialogContent
          id="ask-thread-list"
          aria-label="Threads"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            threadsTriggerRef.current?.focus();
          }}
          className="left-auto right-0 top-0 flex h-dvh w-[340px] max-w-[85vw] translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none border-y-0 border-r-0 bg-[var(--bg-elevated)] p-0"
        >
          <div className="flex shrink-0 items-center border-b border-[var(--border)] px-4 py-3 pr-14">
            <DialogTitle className="text-sm">Threads</DialogTitle>
          </div>
          <div className="flex-1 overflow-y-auto px-3 py-3">
            {threadListLoading ? (
              <p className="px-2 text-xs text-muted-foreground" role="status">Loading threads…</p>
            ) : threadListError ? (
              <div role="alert" className="px-2">
                <p className="error-text mb-2 text-xs">{threadListError}</p>
                <button type="button" className="btn btn-sm" onClick={loadThreads}>Retry</button>
              </div>
            ) : threadList.length === 0 ? (
              <p className="px-2 text-xs text-muted-foreground">
                {isDemo() ? "Demo conversations stay in this browser session." : "No threads yet."}
              </p>
            ) : (
              <ul className="space-y-0.5">
                {threadList.map((t) => (
                  <li key={t.id}>
                    <button
                      type="button"
                      className="w-full rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-[var(--bg-hover)]"
                      onClick={() => void openThread(t.id)}
                      disabled={pending || openingThreadId !== null}
                    >
                      <span className="block truncate font-medium">
                        {openingThreadId === t.id ? "Loading…" : t.title}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                        {t.shared ? "shared" : "private"}
                        {typeof t.turns === "number" ? ` · ${t.turns} turns` : ""}
                        {t.shared && t.created_by_name ? ` · by ${t.created_by_name}` : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {shareNotices.length > 0 && (
        <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-2">
          {shareNotices.map((n) => (
            <div
              key={n.id}
              className="card mb-2 flex items-center justify-between gap-3"
              style={{ padding: "10px 14px" }}
              role="status"
            >
              <span className="text-sm">
                {n.type === "thread.mention" ? (
                  <>
                    <strong>{(n.payload as { mentioned_by?: string }).mentioned_by ?? "A teammate"}</strong>{" "}
                    mentioned you in{" "}
                    <button
                      type="button"
                      className="font-semibold underline"
                      disabled={pending}
                      onClick={async () => {
                        const tid = (n.payload as { thread_id?: string }).thread_id;
                        if (!tid) {
                          setThreadActionError("This mention does not include a valid thread link.");
                          return;
                        }
                        if (await openThread(tid)) await dismissNotice(n.id);
                      }}
                    >
                      {n.payload.title ?? "a thread"}
                    </button>
                  </>
                ) : (
                  <>
                    <strong>{n.payload.shared_by ?? "A teammate"}</strong> shared{" "}
                    <strong>{n.payload.title ?? "a file"}</strong> with you - you can ask
                    about it here.
                  </>
                )}
              </span>
              <button
                type="button"
                className="btn"
                onClick={() => void dismissNotice(n.id)}
                aria-label="Dismiss notification"
              >
                Got it
              </button>
            </div>
          ))}
        </div>
      )}

      {empty ? (
        /* EMPTY STATE */
        <div className="ask-scroll flex-1">
          <div className="flex min-h-full items-center justify-center px-4 py-8">
            <div className="ask-column flex w-full max-w-[760px] flex-col gap-8 text-left">
              {/* Heading */}
              <div className="ask-empty-heading">
                <SheldonMascot state="thinking" size={112} priority />
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
                <div className="ask-composer ask-composer-hero" style={{ position: "relative" }}>
                  <div className="flex items-center gap-3 px-4 py-3">
                    <ComposerAttach onUploaded={handleUploaded} onError={handleUploadError} disabled={pending || demo} />
                    <Textarea
                      ref={inputRef}
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={handleKeyDown}
                      rows={1}
                      maxLength={inputMaxLength}
                      placeholder={activeMode.placeholder}
                      aria-label="Ask Sheldon prompt"
                      className="max-h-44 min-h-[44px] flex-1 resize-none self-center border-0 bg-transparent px-1 py-1 text-base shadow-none outline-none focus-visible:ring-0 placeholder:text-[var(--text-muted)]"
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
                {demo && (
                  <p className="mt-2 text-center text-xs text-muted-foreground">
                    File uploads are disabled in the shared demo.
                  </p>
                )}
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
                    aria-label="Choose how Sheldon should help"
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
                  {COMPOSER_MODES.map((composerMode) => (
                    <TabsContent
                      key={composerMode.id}
                      value={composerMode.id}
                      className="sr-only"
                    >
                      {composerMode.placeholder}
                    </TabsContent>
                  ))}
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

              {/* Recommended workflows: curated examples that name specific tools
                  (Notion/Slack/Freshdesk). Shown only in the demo, where those
                  tools are connected - a real org shouldn't see hardcoded prompts
                  for apps it hasn't connected. (Future: generate these live from
                  the org's connected tools.) */}
              {isDemo() && (
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
              )}

              {/* Disclaimer */}
              <p className="ask-disclaimer">
                Sheldon can make mistakes. Actions that change your tools always
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
            className="ask-scroll min-h-[320px] flex-1 overflow-y-auto"
          >
            <div className="ask-thread mx-auto w-full max-w-3xl space-y-7 py-2">
              {turns.map((t) => (
                <MessageBubble
                  key={t.id}
                  turn={t}
                  busyActions={busyActions}
                  onApprove={handleApprove}
                  onDismiss={handleDismiss}
                />
              ))}
              {pending && (
                <div className="ask-loading-row" role="status" aria-live="polite">
                  <SheldonMascot state="searching" size={48} className="ask-loading-mascot" />
                  <div className="ask-loading-copy">
                    <span className="ask-loading-title">
                      <Loader2 className="size-4 animate-spin" />
                      Searching your workspace
                    </span>
                    <span className="ask-loading-detail">
                      Checking connected sources for relevant context.
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Composer pinned to the bottom of the thread */}
          <form onSubmit={handleSubmit} className="shrink-0 pt-4">
            <div className="ask-conversation-composer mx-auto w-full max-w-3xl">
              <div
                className="ask-composer flex items-center gap-2 px-4 py-3"
                style={{ position: "relative" }}
              >
                <ComposerAttach onUploaded={handleUploaded} onError={handleUploadError} disabled={pending || demo} />
                <Textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  rows={1}
                  maxLength={inputMaxLength}
                  placeholder={mode === "search" ? "Search again..." : "Ask a follow-up..."}
                  aria-label="Ask Sheldon follow-up prompt"
                  className="max-h-40 min-h-[40px] flex-1 resize-none self-center border-0 bg-transparent px-1 py-1.5 text-sm shadow-none outline-none focus-visible:ring-0 placeholder:text-[var(--text-muted)]"
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
              {demo && (
                <p className="mt-2 text-center text-xs text-muted-foreground">
                  File uploads are disabled in the shared demo.
                </p>
              )}
              <p className="ask-disclaimer mt-2 text-center">
                Sheldon can make mistakes. Actions that change your tools always
                require approval.
              </p>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
