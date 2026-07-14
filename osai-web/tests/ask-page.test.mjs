import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../app/ask/page.tsx", import.meta.url), "utf8");

test("Ask uses accessible modes and never blocks the demo on the live API", () => {
  assert.match(page, /<TabsList[\s\S]+aria-label="Choose how Sheldon should help"/);
  assert.match(page, /<TabsTrigger[\s\S]+value={m\.id}/);
  assert.match(page, /placeholder={activeMode\.placeholder}/);
  // The demo answers with the live LLM (askOsai sends X-Org-Id: demo-org) so
  // demo questions get real, varied answers…
  assert.match(page, /const res = await askOsai\(q, {[\s\S]*?}\);/);
  // …but a slow/unreachable backend falls back to canned demo answers in the
  // catch, so the demo never hangs on an error.
  assert.match(page, /catch {[\s\S]+if \(isDemo\(\)\) {[\s\S]+getDemoAnswer\(q\)/);
  assert.match(page, /if \(isDemo\(\)\) {[\s\S]+status: "executed"[\s\S]+return;/);
});
