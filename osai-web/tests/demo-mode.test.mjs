import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// Source contracts for demo-mode isolation (Linear SHE-5 + QA E-03/E-11).
// These pin the browser-side guarantees: no token key for the demo session,
// and DEMO_* fixtures can never leak into a signed-in customer workspace.

const demoLib = await readFile(new URL("../lib/demo.ts", import.meta.url), "utf8");
const demoPage = await readFile(new URL("../app/demo/page.tsx", import.meta.url), "utf8");
const api = await readFile(new URL("../lib/api.ts", import.meta.url), "utf8");

test("isDemo: a real signed-in org wins over the env flag and stale demo keys (SHE-5)", () => {
  // The signed-in check must run before any demo signal is consulted.
  const signedInIdx = demoLib.indexOf("signedInRealOrg");
  const envFlagIdx = demoLib.indexOf('process.env.NEXT_PUBLIC_OSAI_DEMO === "1" ||');
  assert.ok(signedInIdx > -1, "isDemo must special-case a signed-in real org");
  assert.ok(envFlagIdx > signedInIdx, "env flag must be consulted only after the signed-in check");
  assert.match(demoLib, /if \(signedInRealOrg\) return false;/);
});

test("Try Demo stores no osai_token key (QA E-03)", () => {
  assert.ok(
    !demoPage.includes('localStorage.setItem("osai_token"'),
    "the demo entry page must not write an osai_token key"
  );
  assert.match(demoPage, /localStorage\.removeItem\("osai_token"\)/);
});

test("signing into a real org clears demo flags and legacy token (SHE-5)", () => {
  const markSignedIn = api.slice(api.indexOf("export function markSignedIn"));
  assert.match(markSignedIn, /removeItem\("osai_demo"\)/);
  assert.match(markSignedIn, /removeItem\("osai_token"\)/);
});
