import { expect, test } from "@playwright/test";

// The pilot golden path, in demo mode: land → enter demo → dashboard renders →
// ask a question and get an answer → integrations page renders. Any failure
// here is a launch blocker by definition.

test("golden path: login → demo → dashboard → ask → integrations", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /welcome to sheldon/i })).toBeVisible();

  // Enter the demo workspace (no account needed).
  await page.getByRole("button", { name: /try demo/i }).click();
  await page.waitForURL(/dashboard/);

  // Dashboard renders real content, not a blank shell.
  await expect(page.locator("h1")).toBeVisible();

  // Ask returns an answer bubble.
  await page.goto("/ask");
  const composer = page.getByRole("textbox").first();
  await composer.fill("Who owns the VPC security setup?");
  await composer.press("Enter");
  // Demo answers are canned but still exercise the full render path.
  await expect(page.locator("[class*=bubble], [class*=turn], [class*=answer]").first()).toBeVisible({
    timeout: 20_000,
  });

  // Integrations page renders its cards.
  await page.goto("/integrations");
  await expect(page.getByRole("heading", { name: /integrations/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /add connector/i })).toBeVisible();
});

test("crashed route shows the error boundary, not a blank page", async ({ page }) => {
  // A non-existent deep route must render Next's 404, never a white screen.
  const response = await page.goto("/this-route-does-not-exist");
  expect(response?.status()).toBe(404);
  await expect(page.locator("body")).not.toBeEmpty();
});
