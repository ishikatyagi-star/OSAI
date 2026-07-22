import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const api = readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");
const team = readFileSync(new URL("../app/team/page.tsx", import.meta.url), "utf8");

test("member removal previews scoped ownership and submits an encoded transfer target", () => {
  assert.match(api, /export type MemberRemovalAssetCounts/);
  assert.match(api, /`\/team\/members\/\$\{userId\}\/removal-impact`/);
  assert.match(api, /transfer_to_user_id=\$\{encodeURIComponent\(transferToUserId\)\}/);
  assert.match(team, /getMemberRemovalImpact\(member\.id, true\)/);
  assert.match(team, /impact\.requires_transfer \? transferTargetId : undefined/);
});

test("member removal dialog shows impact and requires an explicit same-team successor", () => {
  assert.match(team, /Removal impact/);
  assert.match(team, /private conversation/);
  assert.match(team, /Transfer ownership to/);
  assert.match(team, /Private[\s\S]*conversations will become visible to them/);
  assert.match(team, /Automations will stay paused/);
  assert.match(
    team,
    /removalImpact\.requires_transfer && !transferTargetId/
  );
  assert.match(team, /No eligible teammate remains/);
});

test("preview and transfer failures remain in the dialog and never imply success", () => {
  assert.match(team, /setRemovalError\(writeErrorMessage\(err\)\)/);
  assert.match(team, /role="alert"/);
  assert.match(team, /structuredMessage/);
  assert.match(team, /setRemovalMember\(null\)/);
});
