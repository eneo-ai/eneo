import { expect, test } from "@playwright/test";

// Smoke coverage for the parity-buildout surfaces: each page loads
// authenticated and shows a marker element from the newly-ported feature.
// Labels are the Swedish defaults (the app's default locale).

test("activate landing renders", async ({ page }) => {
  await page.goto("/activate");
  await expect(page.getByText(/nästan klar/i)).toBeVisible();
});

test("account shows the change-password card", async ({ page }) => {
  await page.goto("/account");
  await expect(page.getByText(/byt lösenord/i).first()).toBeVisible();
  await expect(page.locator('input[autocomplete="new-password"]').first()).toBeVisible();
});

test("admin usage has a per-user tab", async ({ page }) => {
  await page.goto("/admin/usage");
  await expect(page.getByRole("tab", { name: /användare/i })).toBeVisible();
});

test("admin insights has a compare toggle + date inputs", async ({ page }) => {
  await page.goto("/admin/insights");
  await expect(page.getByRole("button", { name: /^jämför$/i })).toBeVisible();
  await expect(page.locator('input[type="date"]').first()).toBeVisible();
});

test("admin models has a migration-history tab", async ({ page }) => {
  await page.goto("/admin/models");
  await expect(page.getByRole("tab", { name: /migreringshistorik/i })).toBeVisible();
});

test("admin api-keys exposes the tenant policy + filters", async ({ page }) => {
  await page.goto("/admin/api-keys");
  await expect(page.getByRole("button", { name: /organisationspolicy/i })).toBeVisible();
});
