import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [dashboard, api] = await Promise.all([
  readFile(new URL("../app/dashboard/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../lib/api.ts", import.meta.url), "utf8"),
]);

test("live dashboard values come from timestamped API metrics", () => {
  assert.match(api, /pending_decisions\?: number/);
  assert.match(api, /pending_actions\?: number/);
  assert.match(api, /recent_decisions\?: Array/);
  assert.match(api, /connector_statuses\?: Array/);
  assert.match(dashboard, /liveMetrics\?\.pending_actions \?\? null/);
  assert.match(dashboard, /liveMetrics\?\.pending_decisions \?\? null/);
  assert.match(dashboard, /liveMetrics\?\.recent_decisions \?\? null/);
  assert.match(dashboard, /availability !== "legacy-unavailable"/);
  assert.match(dashboard, /connector\.auth_state === "connected"/);
  assert.match(dashboard, /typeof s\.value === "number"[\s\S]*"Unavailable"/);
  assert.match(dashboard, /Metrics as of <time dateTime=\{liveMetrics\.as_of\}>/);
});

test("indexed documents are not presented as connector health", () => {
  assert.match(dashboard, /Connector Connections/);
  assert.match(dashboard, /connector\.auth_state/);
  assert.doesNotMatch(dashboard, /Object\.entries\(liveByConnector\)/);
  assert.doesNotMatch(dashboard, /Connector Health/);
});
