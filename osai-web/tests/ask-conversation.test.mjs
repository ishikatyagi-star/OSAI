import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../app/ask/page.tsx", import.meta.url), "utf8");
const artifacts = await readFile(
  new URL("../lib/openui-artifacts.ts", import.meta.url),
  "utf8",
);
const citations = await readFile(
  new URL("../components/ask/citation-chip.tsx", import.meta.url),
  "utf8",
);
const actionCard = await readFile(
  new URL("../components/ask/action-card.tsx", import.meta.url),
  "utf8",
);
const messageBubble = await readFile(
  new URL("../components/ask/message-bubble.tsx", import.meta.url),
  "utf8",
);
const api = await readFile(new URL("../lib/api.ts", import.meta.url), "utf8");

test("answers keep the app shell fixed and avoid duplicate generated cards", () => {
  assert.match(page, /focus\(\{ preventScroll: true \}\)/);
  assert.match(artifacts, /return response\.ui_artifacts \?\? \[\];/);
  assert.doesNotMatch(artifacts, /OpenUI answer workspace|Source evidence|Approval queue/);
  assert.match(citations, /inline-flex max-w-full min-w-0/);
  assert.doesNotMatch(citations, /max-w-\[220px\]/);
  assert.match(page, /data-conversation={!empty}/);
  assert.match(page, /aria-label="New chat"/);
  assert.match(page, /ask-new-chat-compact/);
  assert.doesNotMatch(page, /<Plus className="size-5 shrink-0/);
  assert.match(actionCard, /action\.action\.replaceAll\("_", " "\)/);
  assert.match(actionCard, /variant="outline"/);
  assert.match(actionCard, /min-w-\[72px\] border-0/);
  assert.doesNotMatch(actionCard, /<dd className="truncate/);
});

test("conversation messages use calm answer typography and a stable loading lane", () => {
  assert.match(page, /className="ask-loading-row" role="status" aria-live="polite"/);
  assert.match(page, /Searching your workspace/);
  assert.match(page, /Checking connected sources for relevant context/);
  assert.match(messageBubble, /className="ask-context-notice" role="note"/);
  assert.doesNotMatch(messageBubble, /Clock|Cpu|latencyMs \/ 1000/);
  assert.doesNotMatch(messageBubble, /ask-assistant-bubble rounded/);
});

test("Ask sends one idempotent server-owned persistence request", () => {
  assert.match(page, /const requestId = crypto\.randomUUID\(\);/);
  assert.match(page, /threadId: isDemo\(\) \? null : threadId/);
  assert.match(page, /requestId: isDemo\(\) \? null : requestId/);
  assert.match(page, /if \(res\.thread_id\) \{[\s\S]*setThreadId\(res\.thread_id\)/);
  assert.doesNotMatch(page, /appendThreadTurn|createThread/);
  assert.match(api, /request_id: opts\.requestId \?\? null/);
  assert.match(page, /res = await askOsai\(q, askOptions\);[\s\S]*res = await askOsai\(q, askOptions\);/);
  assert.match(page, /error\.name === "AbortError"/);
  assert.match(page, /error instanceof ApiError && error\.status === 503/);
});

test("reloaded Ask threads hydrate the full trusted response", () => {
  assert.match(page, /const stored = turn\.payload\?\.ask_response/);
  assert.match(page, /content: turn\.content,[\s\S]*question,[\s\S]*conversationId/);
  assert.match(page, /conversationId: response\?\.conversation_id/);
  assert.match(page, /response\?\.citations/);
  assert.match(page, /actions: response\?\.actions_taken/);
  assert.match(page, /enoughContext: response\?\.enough_context/);
  assert.match(page, /modelRoute: response\?\.model_route/);
  assert.match(page, /latencyMs: response\?\.latency_ms/);
  assert.match(page, /artifacts: response \? buildOpenUiArtifacts\(response\) : undefined/);
  assert.match(page, /setTurns\(hydrateThreadTurns\(t\.turns\)\)/);
});

test("pending Ask responses cannot be moved into another conversation", () => {
  assert.match(page, /async function openThread\(tid: string\) \{\s*if \(pending \|\| openingThreadId\) return false;/);
  assert.match(page, /async function toggleThreads\(\) \{\s*if \(pending\) return;/);
  assert.match(page, /aria-label="Threads"[\s\S]{0,180}disabled=\{pending\}/);
  assert.match(page, /aria-label="New chat"[\s\S]{0,300}disabled=\{pending\}/);
  assert.match(page, /onClick=\{\(\) => void openThread\(t\.id\)\}[\s\S]{0,100}disabled=\{pending \|\| openingThreadId !== null\}/);
});

test("closing the Threads dialog restores focus to its real opening button", () => {
  assert.match(page, /const threadsTriggerRef = useRef<HTMLButtonElement>\(null\);/);
  assert.match(page, /<button\s+ref=\{threadsTriggerRef\}[\s\S]{0,120}aria-label="Threads"/);
  assert.match(page, /onCloseAutoFocus=\{\(event\) => \{[\s\S]*event\.preventDefault\(\);[\s\S]*threadsTriggerRef\.current\?\.focus\(\);/);
});
