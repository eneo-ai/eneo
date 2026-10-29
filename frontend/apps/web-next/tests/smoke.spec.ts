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

// Fonts (src/app/globals.css "2b. Fonts"): self-hosted, only the UI font preloaded.

test("preloads only Figtree and renders with it", async ({ page }) => {
  const response = await page.goto("/spaces/personal/chat");
  // Next's font loader sent its preloads only as a Link header; Next mirrors
  // the app's own HTML preload into that header too. Both count, once each.
  const headerPreloads = (response?.headers()["link"] ?? "")
    .split(/,\s*(?=<)/)
    .filter((entry) => /rel=preload/.test(entry) && /as="?font/.test(entry))
    .map((entry) => entry.slice(1, entry.indexOf(">")));
  const htmlPreloads = await page
    .locator('link[rel="preload"][as="font"]')
    .evaluateAll((links) => links.map((link) => link.getAttribute("href")));
  const preloads = [...new Set([...headerPreloads, ...htmlPreloads])];
  expect(preloads).toEqual(["/fonts/figtree-latin-wght-normal.woff2"]);
  expect(preloads.join()).not.toMatch(/jetbrains|source-serif/);

  await expect
    .poll(() =>
      page.evaluate(async () => {
        await document.fonts.ready;
        return document.fonts.check("16px Figtree");
      })
    )
    .toBe(true);
  // The UI text picks it (Tailwind's base font, via the theme's --font-figtree).
  expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily)).toMatch(
    /^"?Figtree"?,/
  );
});

// App shell (SideNav, ⌘K palette, phone drawer).

test("profile language selection reloads the document in either language", async ({ page }) => {
  await page.goto("/spaces/list");
  for (const selection of [
    { profile: /: konto och inställningar$/, menu: "Språk", label: "English", locale: "en" },
    { profile: /: account and settings$/, menu: "Language", label: "Svenska", locale: "sv" }
  ]) {
    await page.evaluate(() => Reflect.set(window, "__localeSmokeDocument", true));
    await page.getByRole("button", { name: selection.profile }).click();
    await page.getByRole("menuitem", { name: selection.menu, exact: true }).click();
    await page.getByRole("menuitemradio", { name: selection.label, exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("lang", selection.locale);
    await expect
      .poll(() => page.evaluate(() => Reflect.get(window, "__localeSmokeDocument")))
      .toBeUndefined();
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("lang", selection.locale);
  }
  await expect(page.getByRole("button", { name: /: konto och inställningar$/ })).toBeVisible();
});

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

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  // Public assets skip the session check (src/proxy.ts matcher), the same as in Vite.
  test("serves the integration logos without a session", async ({ request }) => {
    const response = await request.get("/integration-logos/sharepoint.png", { maxRedirects: 0 });
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toBe("image/png");
  });
});
