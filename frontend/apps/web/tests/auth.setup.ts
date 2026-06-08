import { expect, test as setup } from "@playwright/test";
import { STORAGE_STATE } from "../playwright.config";

// Central flow #1: log in through the real UI against the isolated test backend,
// then persist the session so the rest of the suite starts authenticated. If
// this breaks, authentication is broken — every other spec depends on it.
const EMAIL = process.env.E2E_USER ?? "e2e@example.com";
const PASSWORD = process.env.E2E_PASSWORD ?? "E2ePassword1!";

setup("authenticate", async ({ page }) => {
  await page.goto("/login");

  await page.locator('input[name="email"]').fill(EMAIL);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.locator('button[type="submit"]').click();

  // Successful login leaves the /login route for the landing page.
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15_000 });
  await expect(page).not.toHaveURL(/\/login/);

  await page.context().storageState({ path: STORAGE_STATE });
});
