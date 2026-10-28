import { expect, test } from "./csp";

const PHONE = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true };

test.describe("Konto on a phone (decision 22)", () => {
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
});

test.describe("the account pages on an iPad held sideways", () => {
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
