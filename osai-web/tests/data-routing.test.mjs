import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  DENY_ALL_DATA_ROUTING,
  dataRoutingEquals,
  parseDataRouting,
} from "../lib/data-routing.ts";

const validPolicy = {
  normal: { allowed_connectors: ["notion", "slack"], llm_allowed: true },
  amber: { allowed_connectors: ["notion"], llm_allowed: false },
  red: { allowed_connectors: [], llm_allowed: false },
};

test("data-routing parser accepts only the complete normalized contract", () => {
  assert.deepEqual(parseDataRouting(validPolicy), validPolicy);

  for (const invalid of [
    null,
    { normal: validPolicy.normal, amber: validPolicy.amber },
    { ...validPolicy, yellow: validPolicy.amber },
    { ...validPolicy, red: { ...validPolicy.red, unknown: true } },
    { ...validPolicy, amber: { ...validPolicy.amber, llm_allowed: "false" } },
    { ...validPolicy, normal: { ...validPolicy.normal, allowed_connectors: ["Slack"] } },
    { ...validPolicy, normal: { ...validPolicy.normal, allowed_connectors: ["slack", "slack"] } },
  ]) {
    assert.throws(() => parseDataRouting(invalid));
  }
});

test("routing equality treats connector destinations as an unordered set", () => {
  const reordered = structuredClone(validPolicy);
  reordered.normal.allowed_connectors.reverse();
  assert.equal(dataRoutingEquals(validPolicy, reordered), true);

  reordered.normal.allowed_connectors.pop();
  assert.equal(dataRoutingEquals(validPolicy, reordered), false);
  assert.equal(
    Object.values(DENY_ALL_DATA_ROUTING).every(
      (policy) => policy.llm_allowed === false && policy.allowed_connectors.length === 0
    ),
    true
  );
});

test("routing API validates both load and save responses", async () => {
  const api = await readFile(new URL("../lib/api.ts", import.meta.url), "utf8");
  assert.match(api, /getDataRouting\(\): Promise<DataRouting>[\s\S]*apiGet<unknown>[\s\S]*parseDataRouting\(payload\)/);
  assert.match(
    api,
    /patchDataRouting\([\s\S]*expectedRouting: DataRouting \| null[\s\S]*expected_routing: DataRouting \| null[\s\S]*parseDataRouting\(payload\)/
  );
  assert.match(api, /async function apiPatch[\s\S]*throw new ApiError/);
});

test("legacy data-routing routes target the canonical integrations tab", async () => {
  const config = await readFile(new URL("../next.config.ts", import.meta.url), "utf8");
  assert.match(config, /source: "\/data-routing", destination: "\/integrations\?tab=routing"/);
  assert.match(config, /source: "\/settings\/data-routing", destination: "\/integrations\?tab=routing"/);
});
