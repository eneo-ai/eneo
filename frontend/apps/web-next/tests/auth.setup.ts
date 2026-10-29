import { expect, test as setup } from "@playwright/test";
import { STORAGE_STATE } from "../playwright.config";
import { E2E_CREDENTIALS } from "./helpers";

// Choose password login explicitly, including on SSO installations, then persist
// the session so the smoke specs start authenticated. If this breaks, auth is broken.
setup("authenticate", async ({ page }) => {
  const legacyRequests: string[] = [];
  if (process.env.E2E_BASE_URL) {
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (/^\/api\/(eneo|chat|jobs|auth)(\/|$)/.test(path)) legacyRequests.push(path);
    });
  }
  await page.goto("/login?showUsernameAndPassword=true&next=%2Fspaces%2Flist");
  await page.locator('input[name="email"]').fill(E2E_CREDENTIALS.username);
  await page.locator('input[name="password"]').fill(E2E_CREDENTIALS.password);
  await page.evaluate(() => {
    Object.assign(window, { eneoLoginDocument: true });
  });
  await page.locator('button[type="submit"]').click();

  // Successful login leaves /login for the page it was asked to continue to...
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15_000 });
  await expect(page).toHaveURL(/\/spaces\/list$/);
  // ...in a new document: nothing of a previous session stays in memory.
  expect(await page.evaluate(() => "eneoLoginDocument" in window)).toBe(false);

  const state = await page.context().storageState({ path: STORAGE_STATE });
  if (process.env.E2E_BASE_URL) {
    expect(
      state.cookies.some((cookie) => ["__Host-eneo_web", "eneo_web"].includes(cookie.name))
    ).toBe(true);
    await expect(page.locator("main#main-content")).toBeVisible();
    expect(legacyRequests, "Vite must call FastAPI directly").toEqual([]);
  }
});
