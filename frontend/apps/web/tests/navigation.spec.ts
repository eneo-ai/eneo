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

// Hover preloading is enabled inside the authenticated shell only. A hovered
// link runs its page load early; the logout link opts out because its load
// clears the session cookies (see routes/(app)/+layout.svelte).
test("hovering in the app shell preloads the page but never runs the logout", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/spaces\/personal\/chat/);
  // SvelteKit attaches its hover listener during hydration; a hover before that is lost.
  await page.waitForLoadState("networkidle");

  const logoutRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/logout")) logoutRequests.push(request.url());
  });

  // The admin layout's load fetches the audit config, so the hover shows up as that request.
  const preloaded = page.waitForRequest((request) =>
    request.url().includes("/api/v1/audit/config")
  );
  await page.locator('header nav a[href$="/admin"]').hover();
  await preloaded;
  await expect(page).toHaveURL(/\/spaces\/personal\/chat/);

  await page.locator('header nav button[aria-haspopup="menu"]').last().click();
  await page.locator('a[href$="/logout"]').hover();
  // SvelteKit debounces hover preloading by 20 ms; leave room for it to fire if it were enabled.
  await page.waitForTimeout(250);

  expect(logoutRequests).toEqual([]);
  await page.goto("/account");
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.locator("main pre").filter({ hasText: /^e2e@example\.com$/ })).toBeVisible();
});
