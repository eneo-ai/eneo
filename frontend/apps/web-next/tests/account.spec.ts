import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp";
import { apiPost, uniqueName } from "./helpers";

const PHONE = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true };

test.describe("Konto on a phone (decision 22)", { tag: "@vite" }, () => {
  test.use(PHONE);

  test("opens from the drawer's profile row, one page of 44 px rows with Logga ut last", async ({
    page
  }) => {
    await page.goto("/spaces/personal/chat");
    await page.getByRole("button", { name: /^(Öppna menyn|Open menu)$/ }).click();
    const drawer = page.getByRole("dialog", { name: /^(Meny|Menu)$/ });
    await drawer.getByRole("link", { name: /: konto och inställningar$/ }).click();
    await expect(page).toHaveURL(/\/account$/);
    await expect(drawer).toBeHidden();

    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1, name: "Konto" })).toBeVisible();
    const rows = main.getByRole("list").getByRole("link");
    expect(await rows.count()).toBeGreaterThanOrEqual(6);
    for (const row of await rows.all()) {
      expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    }
    const logout = main.getByRole("button", { name: "Logga ut" });
    expect((await logout.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390
    );
  });

  test("sets the theme on Utseende och språk, and Konto says which", async ({ page }) => {
    await page.addInitScript(() => {
      if (!sessionStorage.getItem("seeded")) {
        localStorage.setItem("theme", "light");
        sessionStorage.setItem("seeded", "1");
      }
    });
    await page.goto("/account");
    await page.getByRole("link", { name: /^Utseende och språk ?, Ljust · Svenska$/ }).click();
    await expect(page.getByRole("link", { name: "Tillbaka till Konto" })).toBeVisible();

    const dark = page.getByRole("radio", { name: "Mörkt" });
    expect((await dark.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await dark.click();
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await page.reload();
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);

    await page.getByRole("link", { name: "Tillbaka till Konto" }).click();
    await expect(
      page.getByRole("link", { name: /^Utseende och språk ?, Mörkt · Svenska$/ })
    ).toBeVisible();
  });

  test("logs out", async ({ page, context }) => {
    // Ends this test's session only: the stored state is read, never written.
    await page.goto("/account");
    await page.getByRole("button", { name: "Logga ut" }).click();
    await expect(page).toHaveURL(/\/login\?message=logout/);
    expect((await context.cookies()).some((cookie) => cookie.name === "eneo_session")).toBe(false);
  });

  test("saves multiple reminder days and searches API keys without page overflow", async ({
    page
  }) => {
    await page.goto("/account/api-keys");
    const toggle = page.getByRole("switch", { name: "Utgångspåminnelser" });
    if (!(await toggle.isChecked())) await toggle.click();
    const days = page.getByRole("textbox", { name: "Påminnelsedagar" });
    await expect(days).toBeVisible();
    let releaseFirstWrite!: () => void;
    const firstWrite = new Promise<void>((resolve) => {
      releaseFirstWrite = resolve;
    });
    let heldFirstWrite = false;
    await page.route("**/api/v1/api-keys/notification-preferences", async (route) => {
      if (
        route.request().method() === "PUT" &&
        route.request().postDataJSON().days_before_expiry &&
        !heldFirstWrite
      ) {
        heldFirstWrite = true;
        await firstWrite;
      }
      await route.continue();
    });
    const started = page.waitForRequest(
      (request) =>
        request.url().endsWith("/api/v1/api-keys/notification-preferences") &&
        request.method() === "PUT" &&
        request.postDataJSON().days_before_expiry?.join(",") === "14,7"
    );
    const saved = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/api-keys/notification-preferences") &&
        response.request().method() === "PUT" &&
        response.status() === 200
    );
    const queuedPresetSaved = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/api-keys/notification-preferences") &&
        response.request().method() === "PUT" &&
        response.request().postDataJSON().days_before_expiry?.join(",") === "60,14,7" &&
        response.status() === 200
    );
    await days.fill("14, 7");
    try {
      await days.press("Tab");
      await started;
      await page.getByRole("button", { name: "Lägg till 60 dagar" }).click();
    } finally {
      releaseFirstWrite();
    }
    await saved;
    await queuedPresetSaved;
    await page.reload();
    await expect(days).toHaveValue("60, 14, 7");
    const presetSaved = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/api-keys/notification-preferences") &&
        response.request().method() === "PUT" &&
        response.status() === 200
    );
    await page.getByRole("button", { name: "Lägg till 30 dagar" }).click();
    await presetSaved;
    await page.reload();
    await expect(days).toHaveValue("60, 30, 14, 7");

    const name = uniqueName("Påminnelseintegration");
    for (let index = 0; index < 4; index += 1) {
      await apiPost(page, "/api-keys", {
        name: `${name} ${index}`,
        key_type: "sk_",
        permission: "read",
        scope_type: "tenant"
      });
    }
    await page.reload();
    await page.getByRole("textbox", { name: "Sök API-nycklar" }).fill(`${name} 3`);
    const table = page.getByRole("table", { name: "API-nycklar" });
    await expect(table.getByText(`${name} 3`, { exact: true })).toBeVisible();
    await expect(table.getByText(`${name} 0`, { exact: true })).toBeHidden();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390
    );
    // Axe uses the workspace's Playwright type; these Page APIs are shared by both versions.
    type AxePage = ConstructorParameters<typeof AxeBuilder>[0]["page"];
    const { violations } = await new AxeBuilder({ page: page as unknown as AxePage })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(violations).toEqual([]);
  });
});

test.describe("the account pages on an iPad held sideways", { tag: "@vite" }, () => {
  test.use({ viewport: { width: 1180, height: 820 }, hasTouch: true });

  test("keep Mitt konto, its tabs and the profile menu", async ({ page }) => {
    await page.goto("/account");
    await expect(page.getByRole("heading", { level: 1, name: "Mitt konto" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Kontoinställningar" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "Konto", exact: true })).toBeHidden();
    await expect(page.getByRole("button", { name: /: konto och inställningar$/ })).toHaveAttribute(
      "aria-haspopup",
      "menu"
    );
  });
});
