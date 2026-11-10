import { expect, test } from "./csp";

test.describe("the admin users list on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("shows a user on the first screen at 320 px, as a row with a 44 px menu", async ({
    page
  }) => {
    await page.setViewportSize({ width: 320, height: 568 });
    await page.goto("/admin/users");
    const list = page.getByRole("list", { name: "Aktiva användare" });
    const first = list.getByRole("listitem").first();
    await expect(first).toBeInViewport();
    await expect(page.getByRole("table")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      320
    );
    const menu = first.getByRole("button", { name: /^Fler åtgärder för / });
    expect((await menu.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  });

  test("filters by username in the Filter sheet and clears it", async ({ page }) => {
    await page.goto("/admin/users");
    const list = page.getByRole("list", { name: "Aktiva användare" });
    await expect(list.getByRole("listitem").first()).toBeVisible();
    await page.getByRole("button", { name: "Filter", exact: true }).click();
    const sheet = page.getByRole("dialog", { name: "Filter" });
    await sheet.getByRole("textbox", { name: "Användarnamn" }).fill("ingen-sadan-anvandare");
    await sheet.getByRole("button", { name: "Klar" }).click();
    await expect(sheet).toBeHidden();
    await expect(page.getByText("Inga användare hittades")).toBeVisible();
    await expect(page.getByRole("button", { name: "Filter (1)", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Rensa filter" }).click();
    await expect(list.getByRole("listitem").first()).toBeVisible();
  });
});

test.describe("the user editor on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("keeps the password reset choice and Save reachable in a short viewport", async ({
    page
  }) => {
    await page.goto("/admin/users");
    const menu = page.getByRole("button", { name: /^Fler åtgärder för / }).first();
    await menu.scrollIntoViewIfNeeded();
    await menu.click();
    await page.getByRole("menuitem", { name: /redigera/i }).click();
    const dialog = page.getByRole("dialog", { name: "Redigera användare" });
    const reset = dialog.getByRole("checkbox", { name: /^Generera ett nytt lösenord/ });
    await expect(reset).toBeEnabled();
    await dialog.getByText("Generera ett nytt lösenord", { exact: true }).click();
    await expect(reset).toBeChecked();

    // The viewport left above an on-screen keyboard. The real submit button
    // must remain reachable and associated with the form in the dialog body.
    await page.setViewportSize({ width: 390, height: 420 });
    await reset.scrollIntoViewIfNeeded();
    await expect(reset).toBeInViewport();
    const save = dialog.getByRole("button", { name: "Spara ändringar" });
    await save.scrollIntoViewIfNeeded();
    await expect(save).toBeInViewport();
    await expect(save).toBeEnabled();
    expect(
      await save.evaluate((element) => {
        const button = element as HTMLButtonElement;
        return (
          button.type === "submit" &&
          button.form === button.closest("dialog")?.querySelector("form")
        );
      })
    ).toBe(true);
    await dialog.getByRole("button", { name: "Avbryt" }).click();
    await expect(dialog).toBeHidden();
  });

  test("takes a tap anywhere on a role's row", async ({ page }) => {
    await page.goto("/admin/users");
    const menu = page.getByRole("button", { name: /^Fler åtgärder för / }).first();
    await menu.scrollIntoViewIfNeeded();
    await menu.click();
    await page.getByRole("menuitem", { name: /redigera/i }).click();
    const dialog = page.getByRole("dialog", { name: "Redigera användare" });
    const group = dialog.getByRole("group", { name: /^(Standardroller|Anpassade roller)$/ }).last();
    const row = group.getByRole("listitem").last();
    const role = row.getByRole("checkbox");
    await expect(role).toBeVisible();
    const before = await role.isChecked();
    // Tap the far end after Playwright has scrolled the row into view and
    // waited for the dialog's opening motion to settle.
    const box = (await row.boundingBox())!;
    await row.tap({ position: { x: box.width - 8, y: box.height / 2 } });
    // Retried: the box is checked once React has re-rendered.
    await expect(role).toBeChecked({ checked: !before });
    // Nothing is saved.
    await dialog.getByRole("button", { name: "Avbryt" }).click();
    await expect(dialog).toBeHidden();
  });
});

test.describe("the admin users table on a tablet", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

  test("fits without scrolling sideways", async ({ page }) => {
    await page.goto("/admin/users");
    const region = page.getByRole("group", { name: "Aktiva användare" });
    await expect(region).toBeVisible();
    expect(await region.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0);
  });
});
