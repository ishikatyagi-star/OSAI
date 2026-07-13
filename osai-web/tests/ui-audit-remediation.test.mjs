import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const [
  appShell,
  sidebar,
  globalCss,
  api,
  redirects,
  automations,
  integrations,
  connectorManager,
  settings,
  universityHtml,
  marketingCss,
  dashboard,
  analytics,
  ask,
  composerAttach,
  wiki,
  sql,
  team,
  workflow,
  artifacts,
] = await Promise.all([
  read("components/app-shell.tsx"),
  read("components/sidebar.tsx"),
  read("app/globals.css"),
  read("lib/api.ts"),
  read("next.config.ts"),
  read("app/automations/page.tsx"),
  read("app/integrations/page.tsx"),
  read("components/integrations/connector-manager.tsx"),
  read("app/settings/page.tsx"),
  read("public/osai.html"),
  read("public/landing-eleven.css"),
  read("app/dashboard/page.tsx"),
  read("app/analytics/page.tsx"),
  read("app/ask/page.tsx"),
  read("components/ask/composer-attach.tsx"),
  read("app/wiki/page.tsx"),
  read("app/sql/page.tsx"),
  read("app/team/page.tsx"),
  read("app/workflows/[id]/page.tsx"),
  read("app/artifacts/page.tsx"),
]);

test("shared shell identifies demo state and exposes mobile navigation", () => {
  assert.match(appShell, /Demo workspace/);
  assert.match(appShell, /workspace-status--demo/);
  assert.match(appShell, /SHELL_EXCLUDED[^;]+\/auth\/callback/s);
  assert.doesNotMatch(appShell, /checkedOrgRef/);
  assert.match(appShell, /if \(!cancelled\) setConnected/);
  assert.match(sidebar, /DialogContent className="mobile-nav-panel"/);
  assert.match(sidebar, /aria-label="Primary navigation"/);
  assert.doesNotMatch(sidebar, /sidebar-logo-version/);
  assert.match(globalCss, /@media \(max-width: 900px\)[\s\S]*\.mobile-nav-trigger/);
  assert.match(globalCss, /\.workspace-status--empty,[\s\S]*\.workspace-status--unavailable\s*\{[^}]*min-height: 44px/s);
});

test("tables preserve readable padding and narrow-screen scrolling", () => {
  assert.match(globalCss, /\.table-scroll\s*{[^}]*overflow-x: auto/s);
  assert.match(globalCss, /\.data-table th\s*{[^}]*padding: 12px 16px/s);
  assert.match(globalCss, /\.data-table td\s*{[^}]*padding: 12px 16px/s);
});

test("frontend distinguishes live failures from legitimate empty states", () => {
  assert.match(api, /throwOnError = false/);
  assert.match(api, /if \(throwOnError\) throw new Error/);
  assert.match(api, /getDashboardMetrics\(strict = false\)/);
  assert.match(api, /getWorkflowRun\(id: string, strict = false\)/);
  assert.match(api, /listThreads\(strict = false\)/);
  assert.match(api, /getThread\(id: string, strict = false\)/);
  assert.match(api, /getWikiRevisions\(id: string, strict = false\)/);
  assert.match(dashboard, /getDashboardMetrics\(true\)/);
  assert.match(dashboard, /Dashboard metrics could not be loaded/);
  assert.match(dashboard, /dashboardReady/);
  assert.match(dashboard, /Loading workspace metrics\.\.\./);
  assert.match(analytics, /error && m/);
  assert.match(analytics, /Retrying/);
});

test("frontend copy contains no mojibake", () => {
  const mojibake = /[\u00c2\u00c3\ufffd]|\u00e2[\u0080-\u00bf\u20ac]|\u00f0[\u0080-\u00bf\u0178]/u;
  assert.doesNotMatch([appShell, sidebar, dashboard, analytics, artifacts, connectorManager, sql, team, wiki].join("\n"), mojibake);
});

test("legacy routes preserve user intent", () => {
  assert.match(redirects, /source: "\/context-inbox", destination: "\/ask"/);
  assert.match(redirects, /source: "\/data-routing", destination: "\/team"/);
  assert.match(redirects, /source: "\/inbox", destination: "\/ask"/);
  assert.match(redirects, /source: "\/settings\/data-routing", destination: "\/team"/);
  assert.match(redirects, /source: "\/workflows", destination: "\/automations"/);
});

test("unsupported side effects do not present false success", () => {
  assert.match(automations, /scheduler required/);
  assert.match(automations, /if \(isDemo\(\)\)[\s\S]*DEMO_WORKFLOW_RUNS/);
  const extractStart = automations.indexOf("async function handleExtract");
  const extractHandler = automations.slice(extractStart, automations.indexOf("async function handleApprove", extractStart));
  assert.ok(extractHandler.indexOf("if (isDemo())") < extractHandler.indexOf("postWorkflow("));
  assert.match(automations, /const approval = await approveActionItem/);
  assert.match(automations, /has_trigger_token: true/);
  assert.match(automations, /onApprove: \(runId: string, itemId: string\) => Promise<boolean>/);
  assert.match(automations, /pendingKey\.endsWith\(`:\$\{id\}`\)/);
  assert.match(automations, /onClick=\{onCancel\} disabled=\{saving\}/);
  assert.match(automations, /disabled=\{isAutomationBusy\(a\.id\) \|\| editingId === a\.id\}[\s\S]*setEditingId/);
  assert.match(settings, /Type <strong>DELETE<\/strong> to confirm/);
  assert.match(settings, /Your account was not deleted/);
  assert.doesNotMatch(universityHtml, /YOUR_APPS_SCRIPT_URL_HERE|Message noted/);
  assert.match(universityHtml, /Direct messages are not connected yet/);
  assert.doesNotMatch(universityHtml, /data:image\/jpeg|hero-pixel-img/);
});

test("shared demo blocks backend mutations with explicit UI messaging", () => {
  assert.equal((ask.match(/disabled=\{pending \|\| demo\}/g) ?? []).length, 2);
  assert.match(ask, /File uploads are disabled in the shared demo/);
  assert.match(composerAttach, /busy \|\| disabled/);
  assert.match(wiki, /disabled=\{demo\}/);
  assert.match(wiki, /Wiki changes are disabled in the shared demo/);
});

test("high-stakes dialogs retain errors and lock duplicate mutations", () => {
  for (const source of [artifacts, wiki, sql]) {
    assert.match(source, /disabled=\{deleteBusy\}/);
    assert.match(source, /role="alert"/);
  }
  assert.match(workflow, /approvalError && <p className="error-text" role="alert"/);
  assert.match(workflow, /\["needs_review", "failed"\]\.includes\(item\.status\)/);
  assert.match(workflow, /item\.status === "failed"[\s\S]*var\(--red\)/);
});

test("thread, source, and team state cannot masquerade as empty or stale", () => {
  assert.match(ask, /getThread\(tid, true\)/);
  assert.match(ask, /listThreads\(true\)/);
  assert.match(ask, /Saved threads could not be loaded/);
  assert.match(ask, /if \(await openThread\(tid\)\) dismissNotice/);
  assert.match(sql, /plannedSourceId !== sourceId/);
  assert.match(sql, /clearPlanState\(\)/);
  assert.match(sql, /savingArtifact/);
  assert.match(team, /const invite = await createInvite/);
  assert.match(team, /const department = await createDepartment/);
  assert.match(team, /addingDepartment/);
  assert.match(wiki, /getWikiRevisions\(id, true\)/);
  assert.match(wiki, /requestId === revisionsRequestRef\.current/);
});

test("integration diagnostics distinguish request failures from empty data", () => {
  assert.match(integrations, /recentRunsError=\{syncRunsError\}/);
  assert.match(connectorManager, /Connection health could not be checked/);
  assert.match(connectorManager, /getHealthcheck\(key, true\)/);
  assert.match(connectorManager, /getConnectorDocuments\(key, true\)/);
  assert.match(connectorManager, /requestId !== healthRequestRef\.current/);
  assert.match(connectorManager, /requestId !== docsRequestRef\.current/);
  assert.match(connectorManager, /if \(demo\)[\s\S]*Sample status for this demo/);
  assert.match(connectorManager, /File-level examples are hidden in the shared demo/);
  assert.match(connectorManager, /Recent syncs[\s\S]*recentRunsLoading[\s\S]*recentRunsError/);
  assert.match(connectorManager, /Synced files could not be loaded/);
  assert.match(integrations, /syncTone/);
  assert.match(integrations, /connectionBusy=/);
  assert.match(connectorManager, /syncTone === "error"/);
  assert.match(connectorManager, /disabled=\{demo \|\| connectionBusy\}/);
});

test("marketing CSS is balanced and supports reduced motion", () => {
  assert.equal((marketingCss.match(/{/g) ?? []).length, (marketingCss.match(/}/g) ?? []).length);
  assert.match(marketingCss, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(marketingCss, /\.landing-university \.nav-mobile-menu\[open\]::before/);
});
