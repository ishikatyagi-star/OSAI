import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("app status badges keep accessible contrast tokens", () => {
  assert.match(css, /\.tier-badge--amber\s*{\s*color: var\(--yellow\);/);
});
