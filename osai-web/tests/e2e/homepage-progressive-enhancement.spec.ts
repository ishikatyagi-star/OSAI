import { expect, test } from "@playwright/test";

test("homepage reveals animated content when IntersectionObserver is unavailable", async ({ page }) => {
  await page.addInitScript(() => {
    Reflect.deleteProperty(window, "IntersectionObserver");
  });

  await page.goto("/");

  await expect(page.locator(".fade-up").first()).toHaveClass(/visible/);
  await expect(page.getByRole("heading", { name: /sheldon acts like an ai-native operating system/i })).toBeVisible();
});

test("homepage stays readable when enhancement initialization fails", async ({ page }) => {
  await page.addInitScript(() => {
    const querySelector = Document.prototype.querySelector;
    Object.defineProperty(Document.prototype, "querySelector", {
      configurable: true,
      value(selectors: string) {
        if (selectors === ".nav-mobile-menu") {
          throw new Error("Forced homepage enhancement failure");
        }
        return querySelector.call(this, selectors);
      },
    });
  });

  await page.goto("/");

  await expect(page.locator("html")).not.toHaveClass(/(?:^|\s)js(?:\s|$)/);
  await expect(page.getByRole("heading", { name: /sheldon acts like an ai-native operating system/i })).toBeVisible();
});
