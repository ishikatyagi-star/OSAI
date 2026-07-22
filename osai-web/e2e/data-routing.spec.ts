import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import {
  expectNoHorizontalOverflow,
  mockEmptyNotificationInbox,
  mockExternalFonts,
  watchRuntimeIssues,
} from "./helpers";

const POLICY = {
  normal: {
    allowed_connectors: ["notion", "slack", "freshdesk", "google_drive"],
    llm_allowed: true,
  },
  amber: { allowed_connectors: ["notion", "google_drive"], llm_allowed: false },
  red: { allowed_connectors: [], llm_allowed: false },
};

const DENY_ALL_POLICY = {
  normal: { allowed_connectors: [], llm_allowed: false },
  amber: { allowed_connectors: [], llm_allowed: false },
  red: { allowed_connectors: [], llm_allowed: false },
};

function sessionPayload(isAdmin: boolean) {
  return {
    user_id: "qa-user",
    email: "qa@example.test",
    display_name: "QA User",
    org_id: "qa-org",
    org_name: "QA Workspace",
    role: isAdmin ? "admin" : "member",
    is_admin: isAdmin,
    data_tier: isAdmin ? "red" : "normal",
    permissions: [],
    department_id: null,
  };
}

async function seedWorkspace(page: Page, isAdmin: boolean, onSessionRequest?: () => void) {
  await mockExternalFonts(page);
  await mockEmptyNotificationInbox(page);
  await page.addInitScript(() => {
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "qa-org");
    localStorage.setItem("osai_org_name", "QA Workspace");
    localStorage.setItem("osai_user_name", "QA User");
  });
  await page.route("**/api/auth/session", (route) => {
    onSessionRequest?.();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(sessionPayload(isAdmin)),
    });
  });

  // The query-backed tab is selected after hydration. Keep the adjacent
  // connector surface deterministic if its initial render begins a load first.
  await page.route("**/api/integrations", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/sync-runs", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/dashboard/metrics", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ documents_by_connector: {} }),
    })
  );
}

test("admin loads, edits, and receives server-confirmed routing policy", async ({ page }) => {
  await seedWorkspace(page, true);
  let saved: unknown = null;
  await page.route("**/api/settings/data-routing", async (route) => {
    if (route.request().method() === "PATCH") {
      saved = await route.request().postDataJSON();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify((saved as { routing: unknown }).routing),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(POLICY),
    });
  });

  const runtime = watchRuntimeIssues(page);
  await page.goto("/integrations?tab=routing");
  await expect(page.getByRole("tab", { name: "Data Routing" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Data-routing policy" })).toBeVisible();

  await page.getByRole("checkbox", { name: "Allow Slack destination for Normal data" }).uncheck();
  await page
    .getByRole("checkbox", { name: "Allow Web search (Composio) destination for Normal data" })
    .check();
  await page.getByRole("checkbox", { name: "Allow cloud LLM processing for Amber data" }).check();
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect(page.getByText("Routing policy saved and confirmed by the server.")).toBeVisible();
  expect(saved).toEqual({
    routing: {
      ...POLICY,
      normal: {
        ...POLICY.normal,
        allowed_connectors: ["notion", "freshdesk", "google_drive", "composio_search"],
      },
      amber: { ...POLICY.amber, llm_allowed: true },
    },
    expected_routing: POLICY,
  });
  runtime.expectClean();
});

test("member sees confirmed routing truth without edit controls", async ({ page }) => {
  await seedWorkspace(page, false);
  let patchCalls = 0;
  await page.route("**/api/settings/data-routing", (route) => {
    if (route.request().method() === "PATCH") patchCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(POLICY),
    });
  });

  const runtime = watchRuntimeIssues(page);
  await page.goto("/integrations?tab=routing");
  await expect(page.getByText("View only. Only workspace admins can change data-routing policy.")).toBeVisible();
  await expect(page.getByText("Cloud LLM:", { exact: false })).toHaveCount(3);
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
  expect(patchCalls).toBe(0);
  runtime.expectClean();
});

test("malformed load response exposes no policy or permissive controls", async ({ page }) => {
  await seedWorkspace(page, true);
  await page.route("**/api/settings/data-routing", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...POLICY, yellow: POLICY.amber }),
    })
  );

  const runtime = watchRuntimeIssues(page);
  await page.goto("/integrations?tab=routing");
  await expect(page.getByText("Stored routing settings are invalid.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Normal" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reset to deny-all" })).toBeVisible();
  runtime.expectClean();
});

test("malformed save response never claims the draft was saved", async ({ page }) => {
  await seedWorkspace(page, true);
  await page.route("**/api/settings/data-routing", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: route.request().method() === "PATCH" ? JSON.stringify({ ok: true }) : JSON.stringify(POLICY),
    })
  );

  const runtime = watchRuntimeIssues(page);
  await page.goto("/integrations?tab=routing");
  await page.getByRole("checkbox", { name: "Allow cloud LLM processing for Amber data" }).check();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(/server still reports the previous policy/i)).toBeVisible();
  await expect(page.getByText(/saved and confirmed by the server/i)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save changes" })).toBeEnabled();
  runtime.expectClean();
});

test("save rejection reloads the policy, retains the draft, and does not refresh role", async ({ page }) => {
  let sessionCalls = 0;
  await seedWorkspace(page, true, () => {
    sessionCalls += 1;
  });
  await page.route("**/api/settings/data-routing", (route) => {
    if (route.request().method() === "PATCH") {
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "temporarily unavailable" }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(POLICY),
    });
  });

  await page.goto("/integrations?tab=routing");
  await page.getByRole("checkbox", { name: "Allow cloud LLM processing for Amber data" }).check();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(/server still reports the previous policy/i)).toBeVisible();
  await expect(page.getByText(/saved and confirmed by the server/i)).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: "Allow cloud LLM processing for Amber data" })).toBeChecked();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeEnabled();
  expect(sessionCalls).toBe(1);
});

test("retry recovers an unavailable initial policy without inventing defaults", async ({ page }) => {
  await seedWorkspace(page, true);
  let reads = 0;
  await page.route("**/api/settings/data-routing", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    reads += 1;
    return route.fulfill({
      status: reads === 1 ? 503 : 200,
      contentType: "application/json",
      body:
        reads === 1
          ? JSON.stringify({ detail: "temporarily unavailable" })
          : JSON.stringify(POLICY),
    });
  });

  await page.goto("/integrations?tab=routing");
  await expect(page.getByText("Routing settings could not be loaded safely.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Normal" })).toHaveCount(0);
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("heading", { name: "Normal" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
  expect(reads).toBe(2);
});

test("admin can explicitly recover an invalid stored policy only with deny-all", async ({ page }) => {
  await seedWorkspace(page, true);
  let saved: unknown = null;
  await page.route("**/api/settings/data-routing", async (route) => {
    if (route.request().method() === "PATCH") {
      saved = await route.request().postDataJSON();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify((saved as { routing: unknown }).routing),
      });
    }
    return route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Stored data-routing settings are invalid." }),
    });
  });

  page.once("dialog", (dialog) => dialog.accept());
  await page.goto("/integrations?tab=routing");
  await page.getByRole("button", { name: "Reset to deny-all" }).click();

  expect(saved).toEqual({ routing: DENY_ALL_POLICY, expected_routing: null });
  await expect(page.getByText("Deny-all routing policy saved and confirmed by the server.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Normal" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Allow cloud LLM processing for Normal data" })).not.toBeChecked();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
});

test("member cannot overwrite an invalid stored policy", async ({ page }) => {
  await seedWorkspace(page, false);
  let patchCalls = 0;
  await page.route("**/api/settings/data-routing", (route) => {
    if (route.request().method() === "PATCH") patchCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...POLICY, yellow: POLICY.amber }),
    });
  });

  await page.goto("/integrations?tab=routing");
  await expect(page.getByText("Stored routing settings are invalid.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Reset to deny-all" })).toHaveCount(0);
  expect(patchCalls).toBe(0);
});

test("lost save response is reconciled as saved only when strict GET confirms it", async ({ page }) => {
  await seedWorkspace(page, true);
  let current = structuredClone(POLICY);
  await page.route("**/api/settings/data-routing", async (route) => {
    if (route.request().method() === "PATCH") {
      const body = (await route.request().postDataJSON()) as { routing: typeof POLICY };
      current = structuredClone(body.routing);
      return route.abort("failed");
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(current),
    });
  });

  await page.goto("/integrations?tab=routing");
  await page.getByRole("checkbox", { name: "Allow cloud LLM processing for Amber data" }).check();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(/active and confirmed after reloading the server state/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: "Allow cloud LLM processing for Amber data" })).toBeChecked();
});

test("a valid server-canonicalized response replaces the submitted draft", async ({ page }) => {
  await seedWorkspace(page, true);
  await page.route("**/api/settings/data-routing", async (route) => {
    if (route.request().method() === "PATCH") {
      const body = (await route.request().postDataJSON()) as { routing: typeof POLICY };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...body.routing,
          normal: {
            ...body.routing.normal,
            allowed_connectors: [
              ...body.routing.normal.allowed_connectors,
              "composio_search",
            ],
          },
        }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(POLICY),
    });
  });

  await page.goto("/integrations?tab=routing");
  await page.getByRole("checkbox", { name: "Allow cloud LLM processing for Amber data" }).check();
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect(page.getByText("Routing policy saved and confirmed by the server.")).toBeVisible();
  await expect(
    page.getByRole("checkbox", {
      name: "Allow Web search (Composio) destination for Normal data",
    })
  ).toBeChecked();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
});

test("unverifiable save locks editing until a reload succeeds", async ({ page }) => {
  await seedWorkspace(page, true);
  let reads = 0;
  await page.route("**/api/settings/data-routing", (route) => {
    if (route.request().method() === "PATCH") return route.abort("failed");
    reads += 1;
    if (reads === 2) return route.abort("failed");
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(POLICY),
    });
  });

  await page.goto("/integrations?tab=routing");
  await page.getByRole("checkbox", { name: "Allow cloud LLM processing for Amber data" }).check();
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect(page.getByText("Save outcome is unknown. Editing is locked.")).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
  await page.getByRole("button", { name: "Reload policy" }).click();
  await expect(page.getByRole("checkbox", { name: "Allow cloud LLM processing for Amber data" })).not.toBeChecked();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
  expect(reads).toBe(3);
});

test("a transient role refresh failure preserves a previously confirmed admin", async ({ page }) => {
  await seedWorkspace(page, true);
  await page.unroute("**/api/auth/session");
  let sessionCalls = 0;
  await page.route("**/api/auth/session", (route) => {
    sessionCalls += 1;
    return route.fulfill({
      status: sessionCalls === 1 ? 200 : 503,
      contentType: "application/json",
      body:
        sessionCalls === 1
          ? JSON.stringify(sessionPayload(true))
          : JSON.stringify({ detail: "temporarily unavailable" }),
    });
  });
  await page.route("**/api/settings/data-routing", (route) =>
    route.fulfill({
      status: route.request().method() === "PATCH" ? 403 : 200,
      contentType: "application/json",
      body:
        route.request().method() === "PATCH"
          ? JSON.stringify({ detail: "Admin role required" })
          : JSON.stringify(POLICY),
    })
  );

  await page.goto("/integrations?tab=routing");
  await page.getByRole("checkbox", { name: "Allow cloud LLM processing for Amber data" }).check();
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect(page.getByText(/Admin access was confirmed earlier/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry permission check" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeEnabled();
  await expect(page.getByText(/server still reports the previous policy/i)).toBeVisible();
  expect(sessionCalls).toBe(2);
});

test("set-equivalent destination order does not create a dirty policy", async ({ page }) => {
  await seedWorkspace(page, true);
  await page.route("**/api/settings/data-routing", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(POLICY) })
  );

  await page.goto("/integrations?tab=routing");
  const notion = page.getByRole("checkbox", { name: "Allow Notion destination for Normal data" });
  await notion.uncheck();
  await notion.check();
  await expect(page.getByText("Unsaved changes")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
});

for (const isAdmin of [true, false]) {
  test(`${isAdmin ? "admin" : "member"} routing passes mobile axe and reflow checks`, async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await seedWorkspace(page, isAdmin);
    await page.route("**/api/settings/data-routing", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(POLICY) })
    );

    await page.goto("/integrations?tab=routing");
    await expect(page.getByRole("heading", { name: "Data-routing policy" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(
      results.violations.filter((violation) =>
        ["serious", "critical"].includes(violation.impact ?? "")
      )
    ).toEqual([]);
  });
}
