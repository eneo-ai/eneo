import { expect, test } from "@playwright/test";

// Central flow #3: an anonymous visitor is gated to login. Runs without the
// shared session so it genuinely tests the unauthenticated redirect.
test.use({ storageState: { cookies: [], origins: [] } });

test("unauthenticated visitor is redirected to login", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/login/);
  await expect(page.locator('input[name="email"]')).toBeVisible();
});
