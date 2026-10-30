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

test("successful password login navigates directly to a server-only module handoff", async ({
  page
}) => {
  const destination = "/module-login?module_key=speech-to-text&state=test-state";
  const errors: string[] = [];
  const navigations: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.route(
    (url) => url.pathname === "/login",
    async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fulfill({
        json: { type: "redirect", status: 302, location: destination }
      });
    }
  );
  await page.route(
    (url) => url.pathname === "/module-login",
    async (route) => {
      if (route.request().isNavigationRequest())
        navigations.push(new URL(route.request().url()).search);
      await route.fulfill({
        contentType: "text/html",
        body: "<!doctype html><html><body><h1>Module handoff received</h1></body></html>"
      });
    }
  );
  await page.goto(`/login?next=${encodeURIComponent(destination)}`);
  await page.locator('input[name="email"]').fill("e2e@example.com");
  await page.locator('input[name="password"]').fill("E2ePassword123!");
  await page.locator('button[type="submit"]').click();

  await expect(page.getByRole("heading", { name: "Module handoff received" })).toBeVisible();
  expect(navigations).toEqual(["?module_key=speech-to-text&state=test-state"]);
  expect(errors).toEqual([]);
});
