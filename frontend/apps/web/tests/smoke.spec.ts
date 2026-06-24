import { expect, test } from "@playwright/test";

// Central flow #3: an anonymous visitor is gated to login. Runs without the
// shared session so it genuinely tests the unauthenticated redirect.
test.use({ storageState: { cookies: [], origins: [] } });

test("unauthenticated visitor is redirected to login", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/login/);
  await expect(page.locator('input[name="email"]')).toBeVisible();
});

test("invalid credentials keep the visitor on the login page", async ({ page }) => {
  await page.goto("/login");

  await page.locator('input[name="email"]').fill("e2e@example.com");
  await page.locator('input[name="password"]').fill("not-the-password");
  await page.locator('button[type="submit"]').click();

  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.locator('input[name="email"]')).toBeVisible();
});
