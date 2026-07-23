import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../app/ask/page.tsx", import.meta.url), "utf8");
const api = await readFile(new URL("../lib/api.ts", import.meta.url), "utf8");

test("Ask uses accessible modes and never blocks the demo on the live API", () => {
  assert.match(page, /<TabsList[\s\S]+aria-label="Choose how Sheldon should help"/);
  assert.match(page, /<TabsTrigger[\s\S]+value={m\.id}/);
  assert.match(page, /placeholder={activeMode\.placeholder}/);
  // The demo answers with the live LLM (askOsai sends X-Org-Id: demo-org) so
  // demo questions get real, varied answers…
  assert.match(page, /const askOptions = \{[\s\S]*?requestId: isDemo\(\) \? null : requestId,[\s\S]*?\};/);
  assert.match(page, /res = await askOsai\(q, askOptions\);/);
  // …but a slow/unreachable backend falls back to canned demo answers in the
  // catch, so the demo never hangs on an error.
  assert.match(page, /catch \(error\) {[\s\S]+if \(isDemo\(\)\) {[\s\S]+getDemoAnswer\(q\)/);
  assert.match(page, /if \(isDemo\(\)\) {[\s\S]+status: "executed"[\s\S]+return;/);
});

test("persisted assistant turns come only from the trusted Ask route", () => {
  assert.match(page, /const askOptions = \{[\s\S]*?threadId: isDemo\(\) \? null : threadId,[\s\S]*?requestId: isDemo\(\) \? null : requestId/);
  assert.doesNotMatch(
    page,
    /appendThreadTurn|createThread/,
    "the browser must not author either side of a persisted Ask exchange"
  );
});

test("composer modes use their distinct backend contracts", () => {
  assert.match(
    api,
    /export function searchOsai\([\s\S]*apiPost<SearchRequest, SearchResponse>\("\/search"/
  );
  assert.match(page, /if \(mode === "search"\) \{[\s\S]*await searchOsai\(q,/);
  assert.match(page, /intent: mode === "action" \? \("action" as const\) : \("ask" as const\)/);
  assert.match(api, /intent: opts\.intent \?\? "ask"/);
  assert.equal(page.match(/maxLength=\{inputMaxLength\}/g)?.length, 2);
  assert.match(page, /Search queries must be between 1 and 4,000 characters\./);
});

test("action dismissal is server-owned and temporary approval outages stay retryable", () => {
  assert.match(
    api,
    /export function dismissAgentAction\([\s\S]*?`\/ask\/actions\/\$\{actionId\}\/dismiss`/
  );
  assert.match(page, /await dismissAgentAction\([\s\S]*?status: retryable \? "proposed" : res\.status/);
  assert.match(page, /const retryable = res\.error === "approval_unavailable"/);
  assert.match(page, /status: retryable \? "proposed" : res\.status,[\s\S]*?requires_confirmation: retryable/);
  assert.match(page, /catch \{[\s\S]*?status: "proposed",[\s\S]*?Couldn't dismiss this action/);
});
