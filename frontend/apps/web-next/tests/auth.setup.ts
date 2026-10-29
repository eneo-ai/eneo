import { expect, test as setup } from "@playwright/test";
import { STORAGE_STATE } from "../playwright.config";

// Choose password login explicitly, including on SSO installations, then persist
// the session so the smoke specs start authenticated. If this breaks, auth is broken.
const EMAIL = process.env.E2E_USER ?? "user@example.com";
const PASSWORD = process.env.E2E_PASSWORD ?? "Password1!";

setup("authenticate", async ({ page }) => {
  await page.goto("/login?showUsernameAndPassword=true&next=%2Fspaces%2Flist");
  await page.locator('input[name="email"]').fill(EMAIL);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.evaluate(() => {
    Object.assign(window, { eneoLoginDocument: true });
  });
  await page.locator('button[type="submit"]').click();

  // Successful login leaves /login for the page it was asked to continue to...
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15_000 });
  await expect(page).toHaveURL(/\/spaces\/list$/);
  // ...in a new document: nothing of a previous session stays in memory.
  expect(await page.evaluate(() => "eneoLoginDocument" in window)).toBe(false);

  await page.context().storageState({ path: STORAGE_STATE });
});
