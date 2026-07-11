import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../app/ask/page.tsx", import.meta.url), "utf8");

test("Ask uses accessible modes and never blocks the demo on the live API", () => {
  assert.match(page, /<TabsList[\s\S]+aria-label="Choose how Sheldon should help"/);
  assert.match(page, /<TabsTrigger[\s\S]+value={m\.id}/);
  assert.match(page, /placeholder={activeMode\.placeholder}/);
  assert.match(page, /isDemo\(\)\s*\? getDemoAnswer\(q\)\s*:\s*await askOsai/);
  assert.match(page, /if \(isDemo\(\)\) {[\s\S]+status: "executed"[\s\S]+return;/);
});
