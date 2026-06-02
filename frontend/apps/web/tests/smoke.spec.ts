import { expect, test } from "@playwright/test";

// Reference E2E test. Needs the full stack running (see TESTING.md). It asserts
// the app boots and routes an unauthenticated visitor to the login page — the
// thinnest possible end-to-end signal that the build is serveable. Grow real
// user-flow specs (login, send a chat message, ...) alongside this file.
test("unauthenticated visitor lands on the login page", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/login/);
  await expect(page).toHaveTitle(/Eneo\.ai/);
});
