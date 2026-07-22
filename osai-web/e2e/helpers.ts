import { expect, type Page } from "@playwright/test";

export async function mockExternalFonts(page: Page) {
  await page.route("https://fonts.googleapis.com/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/css", body: "" })
  );
  await page.route("https://fonts.gstatic.com/**", (route) =>
    route.fulfill({ status: 204, body: "" })
  );
}

export async function mockEmptyNotificationInbox(page: Page) {
  await page.route("**/api/notifications/page?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [],
        next_cursor: null,
        total: 0,
        unread_count: 0,
      }),
    })
  );
}

export async function seedDemoWorkspace(page: Page) {
  await mockExternalFonts(page);
  await page.addInitScript(() => {
    localStorage.removeItem("osai_token");
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "demo-org");
    localStorage.setItem("osai_org_name", "Intellact AI");
    localStorage.setItem("osai_user_email", "admin@intellactai.com");
    localStorage.setItem("osai_user_name", "Admin");
  });
}

export function watchRuntimeIssues(page: Page) {
  const issues: string[] = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      issues.push(`console: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => issues.push(`pageerror: ${error.message}`));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (
      ["127.0.0.1", "localhost"].includes(url.hostname) &&
      response.status() >= 400
    ) {
      issues.push(`http ${response.status()}: ${url.pathname}${url.search}`);
    }
  });

  return {
    expectClean() {
      expect(issues, issues.join("\n")).toEqual([]);
    },
  };
}

export async function expectNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
}

export async function openDemoRoute(page: Page, path: string) {
  await seedDemoWorkspace(page);
  await page.goto(path);
  await expect(page.getByText("Demo workspace", { exact: false }).first()).toBeVisible();
}
