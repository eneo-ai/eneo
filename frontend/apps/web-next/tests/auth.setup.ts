import { expect, test as setup } from "@playwright/test";
import { STORAGE_STATE } from "../playwright.config";

// Log in through the real password-login form (which invokes the server action
// and sets the encrypted session cookie), then persist the session so the smoke
// specs start authenticated. If this breaks, auth is broken.
const EMAIL = process.env.E2E_USER ?? "user@example.com";
const PASSWORD = process.env.E2E_PASSWORD ?? "Password1!";

setup("authenticate", async ({ page }) => {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(EMAIL);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.locator('button[type="submit"]').click();

  // Successful login leaves /login for the landing page.
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15_000 });
  await expect(page).not.toHaveURL(/\/login/);

  await page.context().storageState({ path: STORAGE_STATE });
});
