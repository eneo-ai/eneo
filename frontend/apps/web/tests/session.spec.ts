import { expect, test } from "@playwright/test";

test("logging out invalidates the authenticated session", async ({ page }) => {
  await page.goto("/logout");

  await expect(page).toHaveURL(/\/login\?.*message=logout/);
  await expect(page.locator('input[name="email"]')).toBeVisible();

  await page.goto("/");

  await expect(page).toHaveURL(/\/login/);
  await expect(page.locator('input[name="password"]')).toBeVisible();
});
