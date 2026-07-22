import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const api = readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");
const team = readFileSync(new URL("../app/team/page.tsx", import.meta.url), "utf8");

test("team lifecycle controls call scoped APIs and describe link-only invites honestly", () => {
  assert.match(api, /apiDelete<\{ revoked: boolean \}>\(`\/team\/invites\/\$\{id\}`\)/);
  assert.match(api, /apiDelete<\{ deleted: boolean \}>\(`\/team\/members\/\$\{userId\}`\)/);
  assert.match(api, /apiPatch<\{ name: string \}/);
  assert.match(api, /apiDelete<\{ deleted: boolean \}>\(`\/team\/departments\/\$\{id\}`\)/);
  assert.match(team, /Create invite link/);
  assert.match(team, /Sheldon does not send an email/);
  assert.match(team, /handleRevokeInvite/);
  assert.match(team, /handleRemoveMember/);
  assert.match(team, /handleRenameDepartment/);
  assert.match(team, /handleRemoveDepartment/);
  assert.match(team, /m\.id === currentUserId/);
});

test("self-role changes refresh the authoritative session before retaining admin controls", () => {
  assert.match(team, /m\.id === currentUserId && patch\.role !== undefined/);
  assert.match(team, /const session = await getSession\(true\)\.catch\(\(\) => null\)/);
  assert.match(team, /setIsAdmin\(admin\)/);
  assert.match(team, /if \(!admin\) \{[\s\S]*setInvites\(\[\]\);[\s\S]*setTab\("members"\)/);
  assert.match(team, /await refresh\(admin\)/);
});
