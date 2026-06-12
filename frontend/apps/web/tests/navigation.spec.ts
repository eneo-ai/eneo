import { expect, test } from "@playwright/test";

test("primary navigation and account menu reach their main destinations", async ({ page }) => {
  await page.goto("/");

  const primaryNavigation = page.locator("header nav");

  await primaryNavigation.locator('a[href$="/spaces/list"]').click();
  await expect(page).toHaveURL(/\/spaces\/list$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  await primaryNavigation.locator('a[href$="/admin"]').click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole("navigation").nth(1)).toBeVisible();

  await page.locator('header nav button[aria-haspopup="menu"]').last().click();
  await page.locator('a[href$="/account"]').click();

  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator("main pre").filter({ hasText: /^e2e@example\.com$/ })).toBeVisible();
});
