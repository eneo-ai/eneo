import { expect, test } from "./csp";

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

// App shell (SideNav, ⌘K palette, phone drawer).

test("the side navigation reaches the assistant catalog", async ({ page }) => {
  await page.goto("/spaces/list");
  const navigation = page.getByRole("navigation", { name: /huvudmeny|main menu/i });
  await navigation.getByRole("link", { name: /^(assistenter|assistants)$/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(
    page.getByRole("heading", { level: 1, name: /assistenter|assistants/i })
  ).toBeVisible();
});

test("Ctrl/⌘+K opens the command palette and Escape closes it", async ({ page }) => {
  await page.goto("/spaces/list");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: /sök i eneo|search eneo/i });
  await expect(palette).toBeVisible();
  await expect(palette.getByRole("combobox")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
});

test.describe("on a phone", () => {
  test.use({
    viewport: { width: 390, height: 844 },
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
  });

  test("stays on the requested page and opens the navigation drawer", async ({ page }) => {
    await page.goto("/spaces/list");
    await expect(page).toHaveURL(/\/spaces\/list$/);
    await page.getByRole("button", { name: /öppna menyn|open menu/i }).click();
    const drawer = page.getByRole("dialog", { name: /^(meny|menu)$/i });
    await expect(drawer.getByRole("navigation", { name: /huvudmeny|main menu/i })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
  });
});
