import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { expectNoHorizontalOverflow, seedDemoWorkspace } from "./helpers";

const routes = [
  { path: "/team", heading: "Team" },
  { path: "/integrations", heading: "Integrations" },
  { path: "/evals", heading: "Evals" },
] as const;

async function expectStablePage(page: Page, path: (typeof routes)[number]["path"]) {
  if (path === "/team") {
    await expect(page.locator(".data-table tbody tr").first()).toBeVisible();
  } else if (path === "/integrations") {
    await expect(page.getByText("Documents Indexed", { exact: true })).toBeVisible();
  } else {
    await expect(page.getByText("demo data", { exact: true })).toBeVisible();
  }
}

for (const viewport of [
  { name: "mobile", width: 375, height: 812 },
  { name: "desktop", width: 1280, height: 900 },
] as const) {
  test(`Team, Integrations, and Evals pass ${viewport.name} accessibility and reflow`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await seedDemoWorkspace(page);

    for (const route of routes) {
      await page.goto(route.path);
      await expect(page.getByRole("heading", { name: route.heading, exact: true })).toBeVisible();
      await expectStablePage(page, route.path);
      await expectNoHorizontalOverflow(page);

      const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        .analyze();
      const serious = results.violations.filter((violation) =>
        ["serious", "critical"].includes(violation.impact ?? "")
      );
      expect(serious).toEqual([]);
    }
  });
}
