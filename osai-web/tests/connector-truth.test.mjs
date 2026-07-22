import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const readWeb = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const [metadata, integrations, manager, qaFixtures] = await Promise.all([
  readWeb("lib/connector-meta.ts"),
  readWeb("app/integrations/page.tsx"),
  readWeb("components/integrations/connector-manager.tsx"),
  readFile(new URL("../../evals/fixtures/qa.json", import.meta.url), "utf8"),
]);

function connectorBlock(key, nextKey) {
  const start = metadata.indexOf(`  ${key}: {`);
  const end = nextKey ? metadata.indexOf(`  ${nextKey}: {`, start) : metadata.indexOf("\n};", start);
  assert.ok(start >= 0 && end > start, `${key} metadata block must exist`);
  return metadata.slice(start, end);
}

test("legacy connector metadata cannot advertise disabled ingestion", () => {
  for (const [key, nextKey] of [
    ["zoom", "linear"],
    ["linear", "confluence"],
    ["confluence", null],
  ]) {
    const block = connectorBlock(key, nextKey);
    assert.match(block, /availability: "legacy-unavailable"/);
    assert.match(block, /description: "Legacy label only\.[^"]+ unavailable/);
  }
  assert.doesNotMatch(metadata, /Receive meeting webhooks|auto-transcribe recordings/);
});

test("OAuth, sync, and disconnect capabilities are evaluated independently", () => {
  assert.match(integrations, /function canOAuthConnect\(connectorKey: string\)/);
  assert.match(integrations, /function canSync\(integration: Integration\)[\s\S]*capabilities\?\.includes\("sync"\)/);
  assert.match(integrations, /availability !== "legacy-unavailable"/);
  assert.match(integrations, /function canDisconnect\(integration: Integration\)[\s\S]*source === "composio"/);
  assert.match(manager, /canOAuthConnect: boolean;[\s\S]*canSync: boolean;[\s\S]*canDisconnect: boolean;/);
  assert.doesNotMatch(manager, /Sheldon cannot index this connector/);
});

test("eval fixtures do not teach the disabled Zoom connector as a current capability", () => {
  const fixtures = JSON.parse(qaFixtures);
  const connectorCase = fixtures.find((fixture) => fixture.id === "qa-03");
  assert.equal(connectorCase?.expected, "Gmail");
  assert.doesNotMatch(qaFixtures, /Zoom connector|Zoom transcripts/);
});
