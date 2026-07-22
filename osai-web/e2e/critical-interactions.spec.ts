import { expect, test, type Page } from "@playwright/test";
import { mockEmptyNotificationInbox, mockExternalFonts } from "./helpers";

const session = {
  user_id: "qa-admin",
  email: "admin@example.com",
  display_name: "QA Admin",
  org_id: "qa-org",
  org_name: "QA Workspace",
  role: "admin",
  is_admin: true,
  data_tier: "red",
  permissions: [],
  department_id: null,
};

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function seedSignedInWorkspace(page: Page) {
  await mockExternalFonts(page);
  await mockEmptyNotificationInbox(page);
  await page.addInitScript(() => {
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "qa-org");
    localStorage.setItem("osai_org_name", "QA Workspace");
    localStorage.setItem("osai_user_id", "qa-admin");
    localStorage.setItem("osai_user_email", "admin@example.com");
    localStorage.setItem("osai_user_name", "QA Admin");
  });
  await page.route("**/api/auth/session", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(session),
    })
  );
}

async function mockAskBootstrap(page: Page) {
  await page.route("**/api/team/departments", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/notifications?unread_only=true", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
}

test("Ask uploads a personal file and changes its access through rendered controls", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);
  await mockAskBootstrap(page);

  let uploadContentType = "";
  let uploadBody = "";
  let accessUpdate: unknown;
  await page.route("**/api/documents/upload", async (route) => {
    expect(route.request().method()).toBe("POST");
    uploadContentType = (await route.request().headerValue("content-type")) ?? "";
    uploadBody = route.request().postDataBuffer()?.toString("utf8") ?? "";
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        documents_indexed: 1,
        vectors_indexed: 1,
        vector_error: null,
        skipped: [],
        visibility: "personal",
        documents: [{ id: "doc-1", title: "qa-notes.txt", data_tier: "normal" }],
      }),
    });
  });
  await page.route("**/api/team/members", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "member-1",
          email: "member@example.com",
          display_name: "QA Member",
          role: "member",
          data_tier: "normal",
          department_id: null,
          department: null,
          status: "active",
        },
      ]),
    })
  );
  await page.route("**/api/documents/doc-1/access", async (route) => {
    expect(route.request().method()).toBe("PATCH");
    accessUpdate = await route.request().postDataJSON();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        visibility: "company",
        shared_with: [],
        department_id: null,
        qdrant_error: null,
      }),
    });
  });

  await page.goto("/ask");
  await page.locator('input[type="file"]').setInputFiles({
    name: "qa-notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("QA browser upload"),
  });

  await expect(page.getByText("qa-notes.txt", { exact: true })).toBeVisible();
  await expect(page.getByText("Only you", { exact: true })).toBeVisible();
  expect(uploadContentType).toContain("multipart/form-data; boundary=");
  expect(uploadBody).toContain('name="files"; filename="qa-notes.txt"');
  expect(uploadBody).toContain("QA browser upload");
  expect(uploadBody).toMatch(/name="visibility"\r?\n\r?\npersonal/);

  await page.getByRole("button", { name: "Options for qa-notes.txt" }).click();
  await page.getByRole("menuitem", { name: "Manage access" }).click();
  const dialog = page.getByRole("dialog", { name: /Share/ });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Whole company").check();
  await dialog.getByRole("button", { name: "Save" }).click();

  await expect.poll(() => accessUpdate).toEqual({ visibility: "company" });
  await expect(dialog).toBeHidden();
  await expect(page.getByText("Whole company", { exact: true })).toBeVisible();
});

test("Ask reports a rejected upload, prevents duplicate submits, and retries the same file", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);
  await mockAskBootstrap(page);

  let uploadCalls = 0;
  const firstUpload = deferred();
  await page.route("**/api/documents/upload", async (route) => {
    uploadCalls += 1;
    if (uploadCalls === 1) {
      await firstUpload.promise;
      return route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Unsupported file type" }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        documents_indexed: 1,
        vectors_indexed: 1,
        vector_error: null,
        skipped: [],
        visibility: "personal",
        documents: [{ id: "doc-retry", title: "retry.md", data_tier: "normal" }],
      }),
    });
  });

  await page.goto("/ask");
  const input = page.locator('input[type="file"]');
  const attach = page.getByRole("button", { name: "Attach files" });
  const file = {
    name: "retry.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("retry this upload"),
  };

  await input.setInputFiles(file);
  await expect(attach).toBeDisabled();
  await input.setInputFiles(file);
  expect(uploadCalls).toBe(1);

  firstUpload.resolve();
  await expect(
    page.getByText(
      "Those files couldn't be ingested - supported types: txt, md, csv, log, pdf, docx.",
      { exact: true }
    )
  ).toBeVisible();
  await expect(attach).toBeEnabled();
  expect(uploadCalls).toBe(1);

  await input.setInputFiles(file);
  await expect(page.getByText("retry.md", { exact: true })).toBeVisible();
  expect(uploadCalls).toBe(2);
});

test("Ask action approval and dismissal stay durable and retry only unavailable claims", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);
  await mockAskBootstrap(page);

  let confirmationBody: unknown;
  let confirmationCalls = 0;
  let retryConfirmationCalls = 0;
  let dismissalCalls = 0;
  let dismissalBody: unknown;
  let releaseConfirmation = () => {};
  const confirmationGate = new Promise<void>((resolve) => {
    releaseConfirmation = resolve;
  });
  const actionRequests: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.includes("/api/ask/actions/")) actionRequests.push(path);
  });
  await page.route("**/api/ask", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer: "I prepared three actions for review.",
        conversation_id: "conversation-1",
        thread_id: "thread-1",
        citations: [],
        actions_taken: [
          {
            id: "action-approve",
            tool: "slack",
            action: "post_message",
            summary: "Post QA update",
            status: "proposed",
            requires_confirmation: true,
            params: { channel: "#qa" },
            external_url: null,
            error: null,
          },
          {
            id: "action-dismiss",
            tool: "freshdesk",
            action: "create_ticket",
            summary: "Open QA ticket",
            status: "proposed",
            requires_confirmation: true,
            params: { priority: "low" },
            external_url: null,
            error: null,
          },
          {
            id: "action-retry",
            tool: "slack",
            action: "post_message",
            summary: "Post retryable QA update",
            status: "proposed",
            requires_confirmation: true,
            params: { channel: "#qa-retry" },
            external_url: null,
            error: null,
          },
        ],
        enough_context: true,
        model_route: "qa-stub",
        latency_ms: 1,
        via: "osai",
      }),
    })
  );
  await page.route("**/api/ask/actions/action-approve/confirm", async (route) => {
    expect(route.request().method()).toBe("POST");
    confirmationCalls += 1;
    confirmationBody = await route.request().postDataJSON();
    await confirmationGate;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "action-approve",
        status: "executed",
        external_url: "https://example.com/qa-message",
        message: "Executed.",
        error: null,
      }),
    });
  });
  await page.route("**/api/ask/actions/action-retry/confirm", async (route) => {
    retryConfirmationCalls += 1;
    if (retryConfirmationCalls === 1) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "action-retry",
          status: "failed",
          external_url: null,
          message: "Approval could not be verified right now. Please try again.",
          error: "approval_unavailable",
        }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "action-retry",
        status: "executed",
        external_url: "https://example.com/qa-retry-message",
        message: "Executed.",
        error: null,
      }),
    });
  });
  await page.route("**/api/ask/actions/action-dismiss/dismiss", async (route) => {
    expect(route.request().method()).toBe("POST");
    dismissalCalls += 1;
    dismissalBody = await route.request().postDataJSON();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        dismissalCalls === 1
          ? {
              id: "action-dismiss",
              status: "failed",
              message: "Approval could not be verified right now. Please try again.",
              error: "approval_unavailable",
            }
          : {
              id: "action-dismiss",
              status: "skipped",
              message: "Action dismissed.",
              error: null,
            }
      ),
    });
  });

  await page.goto("/ask");
  await page.getByLabel("Ask Sheldon prompt").fill("Prepare two harmless QA actions");
  await page.getByRole("button", { name: "Send" }).click();

  const approvedCard = page.locator(".ask-action-card").filter({ hasText: "Post QA update" });
  const dismissedCard = page.locator(".ask-action-card").filter({ hasText: "Open QA ticket" });
  const retryCard = page
    .locator(".ask-action-card")
    .filter({ hasText: "Post retryable QA update" });
  await approvedCard.getByRole("button", { name: "Approve" }).click();
  await expect(approvedCard.getByRole("button", { name: /Approving/ })).toBeDisabled();
  expect(confirmationCalls).toBe(1);
  expect(confirmationBody).toEqual({ conversation_id: "conversation-1" });

  await retryCard.getByRole("button", { name: "Approve" }).click();
  await expect(retryCard.getByText("Needs approval", { exact: true })).toBeVisible();
  await expect(retryCard.getByRole("alert")).toContainText(
    "Approval could not be verified right now."
  );
  await expect(retryCard.getByRole("button", { name: "Approve" })).toBeEnabled();
  await expect(retryCard.getByText("Executed", { exact: true })).toHaveCount(0);
  await expect(approvedCard.getByRole("button", { name: /Approving/ })).toBeDisabled();
  expect(confirmationCalls).toBe(1);
  releaseConfirmation();
  await expect(approvedCard.getByText("Executed", { exact: true })).toBeVisible();
  await retryCard.getByRole("button", { name: "Approve" }).click();
  await expect(retryCard.getByText("Executed", { exact: true })).toBeVisible();
  await expect(retryCard.locator('[aria-live="polite"]')).toContainText("Executed");
  expect(retryConfirmationCalls).toBe(2);

  await dismissedCard.getByRole("button", { name: "Dismiss" }).click();
  await expect(dismissedCard.getByText("Needs approval", { exact: true })).toBeVisible();
  await expect(dismissedCard.getByRole("button", { name: "Dismiss" })).toBeEnabled();
  await dismissedCard.getByRole("button", { name: "Dismiss" }).click();
  await expect(dismissedCard.getByText("Dismissed", { exact: true })).toBeVisible();
  expect(confirmationCalls).toBe(1);
  expect(dismissalCalls).toBe(2);
  expect(dismissalBody).toEqual({ conversation_id: "conversation-1" });
  expect(actionRequests).toEqual([
    "/api/ask/actions/action-approve/confirm",
    "/api/ask/actions/action-retry/confirm",
    "/api/ask/actions/action-retry/confirm",
    "/api/ask/actions/action-dismiss/dismiss",
    "/api/ask/actions/action-dismiss/dismiss",
  ]);
});

test("Ask follow-ups bound history to the backend contract", async ({ page }) => {
  await seedSignedInWorkspace(page);
  await mockAskBootstrap(page);

  const requestBodies: Array<{
    history?: Array<{ role: string; content: string }>;
  }> = [];
  let askCalls = 0;
  const longAnswer = "L".repeat(4_500);
  await page.route("**/api/ask", async (route) => {
    const body = (await route.request().postDataJSON()) as (typeof requestBodies)[number];
    requestBodies.push(body);
    const invalidHistory =
      (body.history?.length ?? 0) > 10 ||
      Boolean(body.history?.some((turn) => turn.content.length > 4_000));
    if (invalidHistory) {
      return route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "History exceeds contract" }),
      });
    }
    askCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer: askCalls === 6 ? longAnswer : `Answer ${askCalls}`,
        conversation_id: "bounded-conversation",
        thread_id: "bounded-thread",
        citations: [],
        actions_taken: [],
        enough_context: true,
        via: "osai",
      }),
    });
  });

  await page.goto("/ask");
  for (let index = 1; index <= 7; index += 1) {
    await page.getByRole("textbox", { name: /Ask Sheldon.*prompt/ }).fill(`Follow-up ${index}`);
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.locator(".ask-assistant-turn")).toHaveCount(index);
  }

  const finalHistory = requestBodies.at(-1)?.history ?? [];
  expect(askCalls).toBe(7);
  expect(finalHistory).toHaveLength(10);
  expect(finalHistory.every((turn) => turn.content.length <= 4_000)).toBe(true);
  expect(finalHistory).toContainEqual({ role: "assistant", content: "L".repeat(4_000) });
});

test("a newly persisted Ask thread can be shared and made private again", async ({ page }) => {
  await seedSignedInWorkspace(page);
  await mockAskBootstrap(page);

  let shared = false;
  const patches: unknown[] = [];
  await page.route("**/api/ask", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer: "This answer is stored in a private thread.",
        conversation_id: "conversation-1",
        thread_id: "thread-1",
        citations: [],
        actions_taken: [],
        enough_context: true,
        via: "osai",
      }),
    })
  );
  await page.route("**/api/threads/thread-1", async (route) => {
    expect(route.request().method()).toBe("PATCH");
    const body = await route.request().postDataJSON();
    patches.push(body);
    shared = Boolean(body.shared);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "thread-1",
        title: "QA thread",
        shared,
        created_by: "qa-admin",
        created_by_name: "QA Admin",
        created_at: "2026-07-22T10:00:00Z",
        updated_at: "2026-07-22T10:00:00Z",
      }),
    });
  });

  await page.goto("/ask");
  await page.getByLabel("Ask Sheldon prompt").fill("Create a thread");
  await page.getByRole("button", { name: "Send" }).click();

  await page.getByRole("button", { name: "Share thread with your org" }).click();
  await expect(page.getByRole("button", { name: "Make thread private" })).toBeVisible();
  await page.getByRole("button", { name: "Make thread private" }).click();
  await expect(page.getByRole("button", { name: "Share thread with your org" })).toBeVisible();
  expect(patches).toEqual([{ shared: true }, { shared: false }]);
});

test("thread sharing keeps its private state after failure and retries without a duplicate PATCH", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);
  await mockAskBootstrap(page);

  await page.route("**/api/ask", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer: "This answer is stored in a private thread.",
        conversation_id: "conversation-retry",
        thread_id: "thread-retry",
        citations: [],
        actions_taken: [],
        enough_context: true,
        via: "osai",
      }),
    })
  );
  let patchCalls = 0;
  const patchBodies: unknown[] = [];
  const firstPatch = deferred();
  await page.route("**/api/threads/thread-retry", async (route) => {
    patchCalls += 1;
    patchBodies.push(await route.request().postDataJSON());
    if (patchCalls === 1) {
      await firstPatch.promise;
      return route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Only the creator can share this thread" }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "thread-retry",
        title: "QA thread",
        shared: true,
        created_by: "qa-admin",
        created_by_name: "QA Admin",
        created_at: "2026-07-22T10:00:00Z",
        updated_at: "2026-07-22T10:00:00Z",
      }),
    });
  });

  await page.goto("/ask");
  await page.getByLabel("Ask Sheldon prompt").fill("Create a retryable thread");
  await page.getByRole("button", { name: "Send" }).click();

  const share = page.getByRole("button", { name: "Share thread with your org" });
  await share.click();
  await expect(share).toBeDisabled();
  await share.evaluate((button: HTMLButtonElement) => button.click());
  expect(patchCalls).toBe(1);

  firstPatch.resolve();
  await expect(page.locator(".card.error-text[role='alert']")).toHaveText(
    "Thread sharing could not be updated. Only the creator can change access."
  );
  await expect(share).toBeEnabled();
  expect(patchCalls).toBe(1);

  await share.click();
  await expect(page.getByRole("button", { name: "Make thread private" })).toBeVisible();
  await expect(page.locator(".card.error-text[role='alert']")).toHaveCount(0);
  expect(patchCalls).toBe(2);
  expect(patchBodies).toEqual([{ shared: true }, { shared: true }]);
});

test("Settings mints and revokes a Slack Ask token, then signs out all sessions", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);

  let mintCalls = 0;
  let revokeCalls = 0;
  let logoutAllCalls = 0;
  await page.route("**/api/settings/slack-ask-token", (route) => {
    if (route.request().method() === "POST") {
      mintCalls += 1;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          token: "qa-token-shown-once",
          request_url_path: "/slack/ask/qa-token-shown-once",
        }),
      });
    }
    expect(route.request().method()).toBe("DELETE");
    revokeCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ revoked: true }),
    });
  });
  await page.route("**/api/auth/logout-all", (route) => {
    expect(route.request().method()).toBe("POST");
    logoutAllCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Set-Cookie": "osai_session=; Max-Age=0; Path=/; HttpOnly" },
      body: JSON.stringify({ revoked: true }),
    });
  });

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Ask from Slack" })).toBeVisible();
  await page.getByRole("button", { name: "Create token" }).click();
  await expect(page.getByText("/slack/ask/qa-token-shown-once", { exact: true })).toBeVisible();
  expect(mintCalls).toBe(1);

  await page.getByRole("button", { name: "Revoke" }).click();
  await expect(page.getByText("/slack/ask/qa-token-shown-once", { exact: true })).toHaveCount(0);
  expect(revokeCalls).toBe(1);

  await page.getByRole("button", { name: "Sign out everywhere" }).click();
  const dialog = page.getByRole("dialog", { name: "Sign out everywhere" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Sign out everywhere" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(logoutAllCalls).toBe(1);
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("osai_authed")))
    .toBeNull();
});

test("Settings reports a Slack token failure, prevents a duplicate mint, and retries", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);

  let mintCalls = 0;
  const firstMint = deferred();
  await page.route("**/api/settings/slack-ask-token", async (route) => {
    expect(route.request().method()).toBe("POST");
    mintCalls += 1;
    if (mintCalls === 1) {
      await firstMint.promise;
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Token store unavailable" }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        token: "qa-token-after-retry",
        request_url_path: "/slack/ask/qa-token-after-retry",
      }),
    });
  });

  await page.goto("/settings");
  const create = page.getByRole("button", { name: "Create token" });
  await expect(create).toBeVisible();
  await create.click();
  await expect(create).toBeDisabled();
  await create.evaluate((button: HTMLButtonElement) => button.click());
  expect(mintCalls).toBe(1);

  firstMint.resolve();
  await expect(page.locator("p.error-text[role='alert']")).toHaveText(
    "The Slack token could not be created. Please try again."
  );
  await expect(create).toBeEnabled();
  expect(mintCalls).toBe(1);

  await create.click();
  await expect(page.getByText("/slack/ask/qa-token-after-retry", { exact: true })).toBeVisible();
  await expect(page.locator("p.error-text[role='alert']")).toHaveCount(0);
  expect(mintCalls).toBe(2);
});

test("failed global logout clears this cookie and warns that other sessions may remain", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);

  let logoutAllCalls = 0;
  let localLogoutCalls = 0;
  let localLogoutCookie = "";
  const firstLogout = deferred();
  await page.route("**/api/auth/logout-all", async (route) => {
    expect(route.request().method()).toBe("POST");
    logoutAllCalls += 1;
    await firstLogout.promise;
    return route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Session store unavailable" }),
    });
  });
  await page.route("**/api/auth/logout", async (route) => {
    expect(route.request().method()).toBe("POST");
    localLogoutCalls += 1;
    localLogoutCookie = (await route.request().headerValue("cookie")) ?? "";
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Set-Cookie": "osai_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax" },
      body: JSON.stringify({ ok: true }),
    });
  });

  await page.goto("/settings");
  await page.context().addCookies([
    {
      name: "osai_session",
      value: "qa-current-device-cookie",
      url: new URL(page.url()).origin,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await page.getByRole("button", { name: "Sign out everywhere" }).click();
  const dialog = page.getByRole("dialog", { name: "Sign out everywhere" });
  const confirm = dialog.getByRole("button", { name: "Sign out everywhere" });
  await confirm.click();
  await expect(confirm).toBeDisabled();
  await confirm.evaluate((button: HTMLButtonElement) => button.click());
  expect(logoutAllCalls).toBe(1);

  firstLogout.resolve();
  await expect(page).toHaveURL(/\/login\?reason=logout_all_failed$/);
  await expect(page.locator(".login-error[role='alert']")).toContainText(
    "could not confirm that your other sessions were revoked"
  );
  expect(logoutAllCalls).toBe(1);
  expect(localLogoutCalls).toBe(1);
  expect(localLogoutCookie).toContain("osai_session=qa-current-device-cookie");
  expect((await page.context().cookies()).some((cookie) => cookie.name === "osai_session")).toBe(
    false
  );
  await expect
    .poll(() =>
      page.evaluate(() =>
        [
          "osai_authed",
          "osai_org_id",
          "osai_org_name",
          "osai_user_id",
          "osai_user_email",
          "osai_user_name",
        ].map((key) => localStorage.getItem(key))
      )
    )
    .toEqual([null, null, null, null, null, null]);
});

test("logout stays signed in with an actionable retry when both server calls fail", async ({
  page,
}) => {
  await seedSignedInWorkspace(page);

  let logoutAllCalls = 0;
  let localLogoutCalls = 0;
  await page.route("**/api/auth/logout-all", (route) => {
    expect(route.request().method()).toBe("POST");
    logoutAllCalls += 1;
    return route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Session store unavailable" }),
    });
  });
  await page.route("**/api/auth/logout", (route) => {
    expect(route.request().method()).toBe("POST");
    localLogoutCalls += 1;
    if (localLogoutCalls === 1) {
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Cookie endpoint unavailable" }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Set-Cookie": "osai_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax" },
      body: JSON.stringify({ ok: true }),
    });
  });

  await page.goto("/settings");
  await page.context().addCookies([
    {
      name: "osai_session",
      value: "qa-still-signed-in-cookie",
      url: new URL(page.url()).origin,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await page.getByRole("button", { name: "Sign out everywhere" }).click();
  const dialog = page.getByRole("dialog", { name: "Sign out everywhere" });
  const confirm = dialog.getByRole("button", { name: "Sign out everywhere" });
  await confirm.click();

  await expect(dialog.getByRole("alert")).toHaveText(
    "No sessions were confirmed signed out. Check your connection and try again."
  );
  await expect(confirm).toBeEnabled();
  await expect(page).toHaveURL(/\/settings$/);
  expect(logoutAllCalls).toBe(1);
  expect(localLogoutCalls).toBe(1);
  expect(await page.evaluate(() => localStorage.getItem("osai_authed"))).toBe("1");
  expect((await page.context().cookies()).some((cookie) => cookie.name === "osai_session")).toBe(
    true
  );

  await confirm.click();
  await expect(page).toHaveURL(/\/login\?reason=logout_all_failed$/);
  await expect(page.locator(".login-error[role='alert']")).toContainText(
    "could not confirm that your other sessions were revoked"
  );
  expect(logoutAllCalls).toBe(2);
  expect(localLogoutCalls).toBe(2);
  expect(await page.evaluate(() => localStorage.getItem("osai_authed"))).toBeNull();
  expect((await page.context().cookies()).some((cookie) => cookie.name === "osai_session")).toBe(
    false
  );
});
