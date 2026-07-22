import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const login = await readFile(new URL("../app/login/page.tsx", import.meta.url), "utf8");
const callback = await readFile(
  new URL("../app/auth/callback/page.tsx", import.meta.url),
  "utf8"
);
const onboarding = await readFile(
  new URL("../app/onboarding/page.tsx", import.meta.url),
  "utf8"
);
const api = await readFile(new URL("../lib/api.ts", import.meta.url), "utf8");
const nextConfig = await readFile(new URL("../next.config.ts", import.meta.url), "utf8");
const team = await readFile(
  new URL("../../osai-backend/api/routes/team.py", import.meta.url),
  "utf8"
);

test("invite links use a fragment and login immediately scrubs it", () => {
  assert.match(team, /\/login#invite=/);
  assert.doesNotMatch(team, /\/login\?invite=/);
  assert.match(login, /new URLSearchParams\(/);
  assert.match(login, /currentUrl\.hash\.startsWith\("#"\)/);
  assert.match(login, /const invite = fragment\.get\("invite"\)/);
  assert.match(login, /setInviteToken\(invite\)/);
  assert.match(login, /fragment\.delete\("invite"\)/);
  assert.match(login, /window\.history\.replaceState/);
  assert.match(login, /const \[oauthReady, setOauthReady\] = useState\(false\)/);
  assert.match(login, /setOauthReady\(true\)/);
  assert.match(login, /disabled=\{!oauthReady\}/);
  assert.doesNotMatch(login, /searchParams\.get\("invite"\)/);
  assert.doesNotMatch(login, /setInvitedEmail|using <strong>\{invitedEmail\}/);
});

test("invite OAuth starts with a top-level POST while ordinary sign-in stays GET", () => {
  const start = api.slice(
    api.indexOf("export function googleSignInUrl"),
    api.indexOf("export function onboardOrg")
  );
  assert.match(login, /action=\{googleSignInUrl\(\)\}/);
  assert.match(login, /method=\{inviteToken \? "post" : "get"\}/);
  assert.match(login, /target="_self"/);
  assert.match(login, /type="hidden" name="invite" value=\{inviteToken\}/);
  assert.doesNotMatch(login, /googleSignInUrl\(inviteToken/);
  assert.match(start, /new URL\(`\$\{API_ORIGIN\}\/auth\/google\/start`\)/);
  assert.doesNotMatch(start, /inviteToken|searchParams\.set\("invite"/);
  assert.doesNotMatch(callback, /inviteToken|params\.get\("invite"\)/);
});

test("CSP permits the API form and its exact Google redirect origin", () => {
  assert.match(
    nextConfig,
    /`form-action 'self' \$\{apiOrigin\} https:\/\/accounts\.google\.com`/
  );
  assert.match(nextConfig, /Chromium also applies form-action[\s\S]*303 destination/);
});

test("public workspace provisioning is hidden when local email login is disabled", () => {
  assert.match(onboarding, /getAuthConfig\(true\)/);
  assert.match(onboarding, /!config\.email_login_enabled[\s\S]*router\.replace\("\/login"\)/);
});
