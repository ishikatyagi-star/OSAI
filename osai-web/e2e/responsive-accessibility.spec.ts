import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import {
  expectNoHorizontalOverflow,
  mockExternalFonts,
  openDemoRoute,
  seedDemoWorkspace,
  watchRuntimeIssues,
} from "./helpers";

test("mobile navigation remains on-screen, keyboard-safe, and functional", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await openDemoRoute(page, "/dashboard");
  const trigger = page.getByRole("button", { name: "Open navigation" });
  await expect(trigger).toBeVisible();
  await trigger.click();

  const dialog = page.getByRole("dialog", { name: "Navigation" });
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(375);
  expect(box!.y + box!.height).toBeLessThanOrEqual(812);

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
  await trigger.click();
  await dialog.getByRole("link", { name: "Decision Log" }).click();
  await expect(page).toHaveURL(/\/decisions$/);
  await expect(page.getByRole("heading", { name: "Decision Log" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("client navigation preserves history and browser back/forward", async ({ page }) => {
  await openDemoRoute(page, "/dashboard");
  await page.getByRole("link", { name: "Analytics" }).click();
  await expect(page).toHaveURL(/\/analytics$/);
  await page.getByRole("link", { name: "Artifacts" }).click();
  await expect(page).toHaveURL(/\/artifacts$/);

  await page.goBack();
  await expect(page).toHaveURL(/\/analytics$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goForward();
  await expect(page).toHaveURL(/\/analytics$/);
});

for (const viewport of [
  { width: 375, height: 812 },
  { width: 768, height: 900 },
  { width: 1280, height: 900 },
]) {
  test(`core pages do not overflow at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await seedDemoWorkspace(page);
    for (const path of ["/dashboard", "/ask", "/decisions", "/automations", "/settings"]) {
      await page.goto(path);
      await expect(page.locator("h1")).toBeVisible();
      await expectNoHorizontalOverflow(page);
    }
  });
}

for (const path of ["/", "/login", "/dashboard", "/ask", "/decisions", "/settings"]) {
  test(`${path} has no serious WCAG A/AA axe violations`, async ({ page }) => {
    // Audit the stable supported state rather than a transient reveal frame
    // whose text is intentionally mid-opacity.
    await page.emulateMedia({ reducedMotion: "reduce" });
    if (path !== "/" && path !== "/login") {
      await seedDemoWorkspace(page);
    } else if (path === "/login") {
      await mockExternalFonts(page);
      await page.route("**/api/auth/config", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ google_enabled: true, email_login_enabled: false }),
        })
      );
    } else {
      await mockExternalFonts(page);
    }
    const runtime = watchRuntimeIssues(page);
    await page.goto(path);
    await expect(page.locator("h1")).toBeVisible();
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    const serious = results.violations.filter((violation) =>
      ["serious", "critical"].includes(violation.impact ?? "")
    );
    expect(serious).toEqual([]);
    runtime.expectClean();
  });
}
