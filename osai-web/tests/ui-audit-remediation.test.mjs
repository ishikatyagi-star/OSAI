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
  connectorCatalog,
  settings,
  universityHtml,
  marketingCss,
  dashboard,
  analytics,
  ask,
  composerAttach,
  sql,
  team,
  workflow,
  artifacts,
  decisions,
  login,
  authCallback,
  evalDashboard,
] = await Promise.all([
  read("components/app-shell.tsx"),
  read("components/sidebar.tsx"),
  read("app/globals.css"),
  read("lib/api.ts"),
  read("next.config.ts"),
  read("app/automations/page.tsx"),
  read("app/integrations/page.tsx"),
  read("components/integrations/connector-manager.tsx"),
  read("components/integrations/add-connector-dialog.tsx"),
  read("app/settings/page.tsx"),
  read("public/osai.html"),
  read("public/landing-eleven.css"),
  read("app/dashboard/page.tsx"),
  read("app/analytics/page.tsx"),
  read("app/ask/page.tsx"),
  read("components/ask/composer-attach.tsx"),
  read("app/sql/page.tsx"),
  read("app/team/page.tsx"),
  read("app/workflows/[id]/page.tsx"),
  read("app/artifacts/page.tsx"),
  read("app/decisions/page.tsx"),
  read("app/login/page.tsx"),
  read("app/auth/callback/page.tsx"),
  read("components/evals/eval-dashboard.tsx"),
]);

test("shared shell identifies demo state and exposes mobile navigation", () => {
  assert.match(appShell, /Demo workspace/);
  assert.match(appShell, /workspace-status--demo/);
  assert.match(appShell, /SHELL_EXCLUDED[^;]+\/auth\/callback/s);
  assert.doesNotMatch(appShell, /checkedOrgRef/);
  assert.match(appShell, /if \(!cancelled\) setConnected/);
  assert.match(sidebar, /DialogContent className="mobile-nav-panel left-0 top-0 translate-x-0 translate-y-0"/);
  assert.match(sidebar, /DialogDescription className="sr-only"/);
  assert.match(sidebar, /aria-label="Primary navigation"/);
  assert.doesNotMatch(sidebar, /sidebar-logo-version/);
  assert.match(sidebar, /async function handleSignOut\(\)[\s\S]*?catch \{[\s\S]*?finally \{[\s\S]*?router\.replace\("\/login"\)/);
  assert.match(globalCss, /@media \(max-width: 900px\)[\s\S]*\.mobile-nav-trigger/);
  assert.match(globalCss, /\.workspace-status--empty,[\s\S]*\.workspace-status--unavailable\s*\{[^}]*min-height: 44px/s);
});

test("repeated row actions expose record-specific accessible names", () => {
  assert.match(decisions, /aria-label=\{`Edit decision: \$\{d\.title\}`\}/);
  assert.match(automations, /aria-label=\{`Run automation now: \$\{brandText\(a\.name\)\}`\}/);
  assert.match(connectorCatalog, /aria-label=\{`Connect \$\{tk\.name \|\| tk\.slug\}`\}/);
  assert.match(integrations, /aria-label=\{`Connect \$\{brandText\(meta\.label\)\}`\}/);
});

test("links to the static landing route use document navigation", () => {
  assert.doesNotMatch(login, /<Link href="\/"/);
  assert.doesNotMatch(authCallback, /<Link href="\/"/);
  assert.equal((login.match(/<a href="\/"/g) ?? []).length, 2);
  assert.equal((authCallback.match(/<a href="\/"/g) ?? []).length, 1);
});

test("OAuth callback credentials are scrubbed before exchange and failure timers are cleaned up", () => {
  const parsed = authCallback.indexOf("new URLSearchParams(hash)");
  const scrubbed = authCallback.indexOf("window.history.replaceState");
  const validated = authCallback.indexOf("if (!token || !orgId)");
  assert.ok(parsed > -1 && scrubbed > parsed && validated > scrubbed);
  assert.match(authCallback, /catch \{[\s\S]*redirectTimer = window\.setTimeout/);
  assert.match(authCallback, /return \(\) => \{[\s\S]*window\.clearTimeout\(redirectTimer\)/);
  assert.match(redirects, /if \(!isDev && !configuredApiOrigin\)[\s\S]*NEXT_PUBLIC_API_BASE_URL is required for production builds/);
});

test("tables preserve readable padding and narrow-screen scrolling", () => {
  assert.match(globalCss, /\.table-scroll\s*{[^}]*overflow-x: auto/s);
  assert.match(globalCss, /\.data-table th\s*{[^}]*padding: 12px 16px/s);
  assert.match(globalCss, /\.data-table td\s*{[^}]*padding: 12px 16px/s);
});

test("frontend distinguishes live failures from legitimate empty states", () => {
  assert.match(api, /throwOnError = false/);
  assert.match(api, /if \(throwOnError\) \{[\s\S]{0,160}throw new ApiError/);
  assert.match(api, /getDashboardMetrics\(strict = false\)/);
  assert.match(api, /getWorkflowRun\(id: string, strict = false\)/);
  assert.match(api, /`\/workflows\/\$\{id\}`,[\s\S]{0,120}strict,[\s\S]{0,40}true/);
  assert.match(api, /listThreads\(strict = false\)/);
  assert.match(api, /getThread\(id: string, strict = false\)/);
  assert.match(dashboard, /getDashboardMetrics\(true\)/);
  assert.match(dashboard, /Dashboard metrics could not be loaded/);
  assert.match(dashboard, /dashboardReady/);
  assert.match(dashboard, /Loading workspace metrics\.\.\./);
  assert.match(analytics, /error && m/);
  assert.match(analytics, /Retrying/);
});

test("live evals require an explicit current-admin POST", () => {
  assert.match(api, /runEvalSuite\(\)[\s\S]*apiPost<Record<string, never>, EvalRun>\("\/evals", \{\}, 180000\)/);
  assert.doesNotMatch(api, /apiGet<EvalRun[^\n]+\("\/evals"/);
  assert.match(evalDashboard, /const session = await getSession\(true\)/);
  assert.match(evalDashboard, /setLoadState\(admin \? "idle" : "forbidden"\)/);
  assert.match(evalDashboard, /may incur provider cost/);
  assert.match(evalDashboard, /onClick=\{runSuite\}/);
  assert.match(evalDashboard, /error instanceof ApiError && \(error\.status === 401 \|\| error\.status === 403\)[\s\S]*setIsAdmin\(false\);[\s\S]*await prepare\(\)/);
  assert.doesNotMatch(evalDashboard, /useEffect\([\s\S]{0,300}runEvalSuite/);
});

test("frontend copy contains no mojibake", () => {
  const mojibake = /[\u00c2\u00c3\ufffd]|\u00e2[\u0080-\u00bf\u20ac]|\u00f0[\u0080-\u00bf\u0178]/u;
  assert.doesNotMatch([appShell, sidebar, dashboard, analytics, artifacts, connectorManager, sql, team].join("\n"), mojibake);
});

test("legacy routes preserve user intent", () => {
  assert.match(redirects, /source: "\/context-inbox", destination: "\/ask"/);
  assert.match(redirects, /source: "\/data-routing", destination: "\/integrations\?tab=routing"/);
  assert.match(redirects, /source: "\/inbox", destination: "\/ask"/);
  assert.match(redirects, /source: "\/settings\/data-routing", destination: "\/integrations\?tab=routing"/);
  assert.match(redirects, /source: "\/workflows", destination: "\/automations"/);
});

test("unsupported side effects do not present false success", () => {
  assert.match(automations, /getCapabilities\(true\)/);
  assert.match(automations, /scheduler unavailable/);
  assert.match(automations, /Connected destinations could not be loaded/);
  const workflowDestinations = automations.match(
    /const WORKFLOW_DESTINATIONS = \[[\s\S]*?\] as const;/,
  )?.[0] ?? "";
  assert.doesNotMatch(workflowDestinations, /google_drive|Google Drive/);
  assert.match(api, /google_drive: "googledrive"/);
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
});

test("high-stakes dialogs retain errors and lock duplicate mutations", () => {
  for (const source of [artifacts, sql]) {
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
  assert.match(ask, /if \(await openThread\(tid\)\) await dismissNotice/);
  assert.match(sql, /plannedSourceId !== sourceId/);
  assert.match(sql, /clearPlanState\(\)/);
  assert.match(sql, /savingArtifact/);
  assert.match(team, /const invite = await createInvite/);
  assert.match(team, /const department = await createDepartment/);
  assert.match(team, /addingDepartment/);
  assert.match(team, /const ROLES = \["admin", "member"\] as const/);
  assert.doesNotMatch(team, /const ROLES = [^\n]*manager/);
  assert.match(team, /m\.role === "admin" && adminCount === 1/);
  assert.match(sql, /getSession\(true\)[\s\S]*const admin = !!session\?\.is_admin/);
  assert.match(sql, /if \(admin\) void reloadSources\(\);[\s\S]*else setLoadingSources\(false\)/);
  assert.match(sql, /\(demo \|\| isAdmin\) && \([\s\S]*Add source/);
  assert.match(sql, /Only workspace admins can connect and query live databases/);
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
  assert.match(connectorCatalog, /role="status" aria-live="polite"/);
  assert.match(connectorCatalog, /The app catalog couldn't be loaded/);
  assert.match(integrations, /window\.confirm\([\s\S]*?removes its indexed documents from Sheldon/);
  assert.match(automations, /item\.auth_state === "connected"/);
  assert.match(automations, /setDestination\("manual"\)/);
});

test("connector catalog promises only supported ingestion sources", () => {
  const copy = [integrations, connectorCatalog].join("\n");
  assert.match(copy, /Gmail, Google Drive, Notion, or Slack/);
  assert.doesNotMatch(copy, /1,000\+|full app catalog|connect any tool/i);
  assert.match(api, /listComposioToolkits[\s\S]*DEFAULT_TIMEOUT_MS,[\s\S]*true/);
  assert.doesNotMatch(copy, /<img/);
  assert.match(integrations, /getSession\(true\)[\s\S]*setIsAdmin/);
  assert.match(integrations, /canManage=\{isAdmin\}/);
  assert.match(connectorManager, /Only workspace admins can sync or change this connection/);
});

test("marketing CSS is balanced and supports reduced motion", () => {
  assert.equal((marketingCss.match(/{/g) ?? []).length, (marketingCss.match(/}/g) ?? []).length);
  assert.match(marketingCss, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(marketingCss, /\.landing-university \.nav-mobile-menu\[open\]::before/);
});
