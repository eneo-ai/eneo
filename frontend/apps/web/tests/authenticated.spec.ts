import { expect, test } from "@playwright/test";

// Central flow #2: a logged-in user (session from auth.setup.ts) reaches the
// app shell. Exercises the authenticated SSR path end-to-end against the real
// backend — exactly the integration that mocked component tests can't verify.
test("authenticated user lands in the personal chat workspace", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/spaces\/personal\/chat/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByRole("navigation").first()).toBeVisible();
});
