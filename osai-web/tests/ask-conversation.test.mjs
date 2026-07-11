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
