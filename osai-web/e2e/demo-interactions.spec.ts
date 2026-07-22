import { expect, test } from "@playwright/test";
import { expectNoHorizontalOverflow, openDemoRoute, watchRuntimeIssues } from "./helpers";

test.describe("demo feature interactions", () => {
  test("Ask, Search, and Take action use distinct backend contracts", async ({ page }) => {
    const searchRequests: Record<string, unknown>[] = [];
    const askRequests: Record<string, unknown>[] = [];
    await page.route("**/api/search", async (route) => {
      searchRequests.push((await route.request().postDataJSON()) as Record<string, unknown>);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "Search found the release checklist.",
          citations: [],
          enough_context: true,
        }),
      });
    });
    await page.route("**/api/ask", async (route) => {
      const body = (await route.request().postDataJSON()) as Record<string, unknown>;
      askRequests.push(body);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: `Handled ${String(body.intent)} intent.`,
          conversation_id: `qa-${String(body.intent)}`,
          citations: [],
          actions_taken: [],
          enough_context: true,
          via: "osai",
        }),
      });
    });

    await openDemoRoute(page, "/ask");
    await page.getByRole("tab", { name: "Search" }).click();
    await page.getByLabel("Ask Sheldon prompt").fill("Find the release checklist");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Search found the release checklist.")).toBeVisible();
    expect(searchRequests).toEqual([
      { org_id: "demo-org", query: "Find the release checklist", department_id: null },
    ]);
    expect(askRequests).toHaveLength(0);

    await page.getByRole("button", { name: "New chat" }).click();
    await page.getByRole("tab", { name: "Take action" }).click();
    await page.getByLabel("Ask Sheldon prompt").fill("Post the release update to Slack");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Handled action intent.")).toBeVisible();
    expect(askRequests[0]).toMatchObject({
      question: "Post the release update to Slack",
      intent: "action",
    });

    await page.getByRole("button", { name: "New chat" }).click();
    await page.getByRole("tab", { name: "Ask" }).click();
    await page.getByLabel("Ask Sheldon prompt").fill("Who owns the release?");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Handled ask intent.")).toBeVisible();
    expect(askRequests[1]).toMatchObject({
      question: "Who owns the release?",
      intent: "ask",
    });
  });

  test("Ask modes, threads, answer flow, and reset work", async ({ page }) => {
    await page.route("**/api/ask", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "VPC security is owned by Priya and is in progress.",
          conversation_id: "qa-conversation",
          citations: [],
          actions_taken: [],
          enough_context: true,
          model_route: "qa-stub",
          latency_ms: 1,
        }),
      })
    );
    const runtime = watchRuntimeIssues(page);
    await openDemoRoute(page, "/ask");

    const prompt = page.getByLabel("Ask Sheldon prompt");
    const send = page.getByRole("button", { name: "Send" });
    await expect(send).toBeDisabled();
    await expect(page.getByRole("button", { name: "Attach files" })).toBeDisabled();

    await page.getByRole("tab", { name: "Search" }).click();
    await expect(prompt).toHaveAttribute("placeholder", "Search connected tools...");
    await page.getByRole("tab", { name: "Take action" }).click();
    await expect(prompt).toHaveAttribute("placeholder", "Describe an action...");
    await page.getByRole("tab", { name: "Ask" }).click();

    const threadsButton = page.getByRole("button", { name: "Threads", exact: true });
    await threadsButton.click();
    const threadsDialog = page.getByRole("dialog", { name: "Threads" });
    await expect(threadsDialog).toBeVisible();
    await expect(page.getByText("Demo conversations stay in this browser session.")).toBeVisible();
    await threadsDialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(threadsButton).toBeFocused();

    await prompt.fill("Who owns the VPC security setup and is it done?");
    await expect(send).toBeEnabled();
    await send.click();
    await expect(page.getByLabel("Ask Sheldon follow-up prompt")).toBeVisible();
    await expect(page.getByRole("button", { name: "New chat" })).toBeVisible();
    await page.getByRole("button", { name: "New chat" }).click();
    await expect(page.getByRole("heading", { name: "What would you like to know?" })).toBeVisible();
    runtime.expectClean();
  });

  test("demo requests omit a stale real-session cookie", async ({ page, context, baseURL }) => {
    expect(baseURL).toBeTruthy();
    await context.addCookies([
      { name: "osai_session", value: "stale-real-token", url: baseURL! },
    ]);

    // Keep the synthetic cookie in the browser after demo's best-effort logout,
    // so the Ask assertion proves credentials are omitted rather than merely
    // proving the cleanup endpoint happened to remove it.
    await page.route("**/api/auth/logout", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: '{"ok":true}' })
    );

    let askHeaders: Record<string, string> | undefined;
    await page.route("**/api/ask", async (route) => {
      askHeaders = await route.request().allHeaders();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "The demo workspace remained isolated.",
          conversation_id: "qa-demo-isolation",
          citations: [],
          actions_taken: [],
          enough_context: true,
          model_route: "qa-stub",
          latency_ms: 1,
        }),
      });
    });

    await page.goto("/demo");
    await expect(page).toHaveURL(/\/dashboard$/);
    await page.goto("/ask");
    await page.getByLabel("Ask Sheldon prompt").fill("Verify demo isolation");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("The demo workspace remained isolated.")).toBeVisible();

    await expect.poll(() => askHeaders?.["x-org-id"]).toBe("demo-org");
    expect(askHeaders?.cookie).toBeUndefined();
  });

  test("negative feedback is accessible, mobile-safe, and honest in demo", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    let feedbackRequests = 0;
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/api/feedback") feedbackRequests += 1;
    });
    await page.route("**/api/ask", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "A test answer that can receive feedback.",
          conversation_id: "qa-feedback",
          citations: [],
          actions_taken: [],
          enough_context: true,
          model_route: "qa-stub",
          latency_ms: 1,
        }),
      })
    );

    await openDemoRoute(page, "/ask");
    await page.getByLabel("Ask Sheldon prompt").fill("Give me a test answer");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("A test answer that can receive feedback.")).toBeVisible();
    await page.getByRole("button", { name: "Bad answer" }).click();

    await expect(page.getByLabel("What was wrong?")).toBeVisible();
    await expect(page.getByLabel("Correct answer")).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.getByLabel("What was wrong?").fill("The source was incomplete");
    await page
      .getByLabel("What was wrong?")
      .locator("..")
      .getByRole("button", { name: "Send", exact: true })
      .click();
    await expect(page.getByText("Demo feedback is not saved")).toBeVisible();
    expect(feedbackRequests).toBe(0);
  });

  test("sign out clears the server cookie and local identity", async ({ page, context, baseURL }) => {
    expect(baseURL).toBeTruthy();
    await context.addCookies([
      { name: "osai_session", value: "real-session-token", url: baseURL! },
    ]);
    await page.addInitScript(() => {
      localStorage.setItem("osai_authed", "1");
      localStorage.setItem("osai_org_id", "real-org");
      localStorage.setItem("osai_org_name", "QA Workspace");
      localStorage.setItem("osai_user_name", "QA User");
      localStorage.setItem("osai_user_email", "qa@example.com");
    });

    let logoutCookie = "";
    await page.route("**/api/dashboard/metrics", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          total_documents: 0,
          documents_by_connector: {},
          documents_by_tier: {},
          connectors_connected: 0,
          sync_runs_total: 0,
          sync_runs_succeeded: 0,
          last_sync_at: null,
          members: 1,
          departments: 0,
          automations: 0,
        }),
      })
    );
    await page.route("**/api/auth/logout", async (route) => {
      logoutCookie = (await route.request().headerValue("cookie")) ?? "";
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "Set-Cookie": "osai_session=; Max-Age=0; Path=/; HttpOnly" },
        body: '{"ok":true}',
      });
    });

    await page.goto("/dashboard");
    await page.getByLabel("QA User profile menu").click();
    await page.getByRole("button", { name: "Sign out" }).last().click();
    await expect(page).toHaveURL(/\/login$/);
    expect(logoutCookie).toContain("osai_session=real-session-token");
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem("osai_authed")))
      .toBeNull();
    await expect
      .poll(async () =>
        (await context.cookies(baseURL!)).some((cookie) => cookie.name === "osai_session")
      )
      .toBe(false);
  });

  test("Decision Log supports local create, edit, filter, sort, and delete", async ({ page }) => {
    await openDemoRoute(page, "/decisions");
    const title = "QA browser decision";

    await page.getByRole("button", { name: "+ Add Decision" }).click();
    await page.getByPlaceholder("Decision title").fill(title);
    await page.getByPlaceholder("Owner").fill("QA Owner");
    await page.getByPlaceholder("Source").fill("Browser test");
    await page.getByPlaceholder("architecture, security").fill("qa, browser");
    await page.getByRole("button", { name: "Save decision" }).click();
    await expect(page.getByText(title, { exact: true })).toBeVisible();

    await page.getByLabel("Search decisions").fill(title);
    await expect(page.getByText(/1 of .* decisions/)).toBeVisible();
    await page.getByRole("button", { name: "Decision", exact: true }).click();

    await page.getByRole("button", { name: `Edit decision: ${title}` }).click();
    await page.getByPlaceholder("Decision title").fill(`${title} edited`);
    await page.getByRole("button", { name: "Save decision" }).click();
    await page.getByLabel("Search decisions").fill("QA browser decision edited");
    await expect(page.getByText(`${title} edited`, { exact: true })).toBeVisible();

    await page.getByRole("button", { name: `Delete decision: ${title} edited` }).click();
    await expect(page.getByRole("heading", { name: "Delete this decision?" })).toBeVisible();
    await page.getByRole("button", { name: "Delete decision", exact: true }).click();
    await expect(page.getByText(`${title} edited`, { exact: true })).toHaveCount(0);
  });

  test("Automations support local create, edit, run, and delete", async ({ page }) => {
    await openDemoRoute(page, "/automations");
    const name = "QA weekly digest";

    await page.getByLabel("Automation name").first().fill(name);
    await page.getByLabel("Automation task prompt").first().fill("Summarize unresolved blockers");
    await page.getByRole("button", { name: "Create automation" }).click();
    await expect(page.getByText(name, { exact: true })).toBeVisible();

    await page.getByRole("button", { name: `Edit automation: ${name}` }).click();
    const editName = page.locator(".automation-edit-form").getByLabel("Automation name");
    await editName.fill(`${name} edited`);
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText(`${name} edited`, { exact: true })).toBeVisible();

    await page.getByRole("button", { name: `Run automation now: ${name} edited` }).click();
    await expect(page.getByText(/Demo run completed|Run complete|completed/i).first()).toBeVisible();

    await page.getByRole("button", { name: `Delete automation: ${name} edited` }).click();
    await expect(page.getByRole("heading", { name: "Delete this automation?" })).toBeVisible();
    await page.getByRole("button", { name: "Delete automation", exact: true }).click();
    await expect(page.getByText(`${name} edited`, { exact: true })).toHaveCount(0);
  });

  test("team and data admin writes are unavailable in the shared demo", async ({ page }) => {
    await openDemoRoute(page, "/team");
    await page.getByRole("tab", { name: "Departments" }).click();
    await expect(page.getByText("Only workspace admins can add departments.")).toBeVisible();
    await expect(page.getByLabel("New department name")).toHaveCount(0);

    await page.getByRole("tab", { name: "Invites" }).click();
    await expect(page.getByText("Only workspace admins can create or view invitations.")).toBeVisible();
    await expect(page.getByLabel("Invite role")).toHaveCount(0);

    await page.goto("/sql");
    await expect(page.getByRole("button", { name: "Add source" })).toBeDisabled();
  });

  test("demo connector truth never advertises the disabled Zoom integration", async ({ page }) => {
    await openDemoRoute(page, "/dashboard");
    await expect(page.getByText("Gmail", { exact: true })).toBeVisible();
    await expect(page.getByText("Zoom", { exact: true })).toHaveCount(0);

    await page.goto("/integrations");
    await expect(page.getByRole("heading", { name: "Integrations" })).toBeVisible();
    await expect(page.getByText("Gmail", { exact: true })).toBeVisible();
    await expect(page.getByText("Zoom", { exact: true })).toHaveCount(0);
  });

  test("danger-zone confirmations are explicit while admin reset stays hidden in demo", async ({ page }) => {
    await openDemoRoute(page, "/settings");

    await expect(page.getByRole("button", { name: "Clear workspace data" })).toHaveCount(0);

    await page.getByRole("button", { name: "Delete account" }).click();
    const deleteDialog = page.getByRole("dialog", { name: "Delete account" });
    await expect(deleteDialog.getByRole("button", { name: "Yes, delete account" })).toBeDisabled();
    await deleteDialog.getByRole("textbox").fill("DELETE");
    await expect(deleteDialog.getByRole("button", { name: "Yes, delete account" })).toBeEnabled();
    await deleteDialog.getByRole("button", { name: "Cancel" }).click();
  });
});
