import { expect, test } from "./csp";

test.describe("the models on a phone (decision 31)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("are rows with their hosting, a switch and a menu; the type opens as a sheet", async ({
    page
  }) => {
    await page.goto("/admin/models");
    // The seeded provider's models (e2e/seed.py).
    const list = page.getByRole("main").getByRole("list", { name: "E2E Mock Provider" });
    await expect(list).toBeVisible();
    await expect(page.getByRole("main").getByRole("table")).toHaveCount(0);
    const row = list.getByRole("listitem").first();
    const toggle = row.getByRole("switch");
    const menu = row.getByRole("button", { name: /^Fler åtgärder för / });
    for (const target of [toggle, menu]) {
      expect((await target.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    }
    // The switch's track sits level with the menu.
    const middle = async (target: typeof toggle) => {
      const box = (await target.boundingBox())!;
      return box.y + box.height / 2;
    };
    expect(Math.abs((await middle(toggle)) - (await middle(menu)))).toBeLessThanOrEqual(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390
    );

    // The type filter is a selector; on touch it opens as a sheet.
    await page.getByRole("combobox", { name: /^Modelltyp/ }).click();
    const options = page.getByRole("listbox");
    await expect(options).toBeVisible();
    await expect(options.getByRole("option").first()).toBeVisible();
    await page.keyboard.press("Escape");
  });
});

test.describe("the models on a tablet", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

  test("keep their table and the type segments", async ({ page }) => {
    await page.goto("/admin/models");
    await expect(page.getByRole("main").getByRole("table").first()).toBeVisible();
    await expect(page.getByRole("radiogroup", { name: "Modelltyp" })).toBeVisible();
  });

  test("keep an open model draft when the screen changes between tablet and phone", async ({
    page
  }) => {
    await page.goto("/admin/models");
    await page
      .getByRole("main")
      .getByRole("button", { name: /^Fler åtgärder för / })
      .first()
      .click();
    await page.getByRole("menuitem", { name: "Redigera", exact: true }).click();
    const dialog = page.getByRole("dialog");
    const description = dialog.getByLabel("Beskrivning", { exact: true });
    await description.fill("Osparad beskrivning efter skärmbyte");
    for (const width of [390, 820]) {
      await page.setViewportSize({ width, height: 844 });
      await expect(dialog).toBeVisible();
      await expect(description).toHaveValue("Osparad beskrivning efter skärmbyte");
      await expect(description).toBeFocused();
    }
    await dialog.getByRole("button", { name: "Avbryt", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(
      page
        .getByRole("main")
        .getByRole("button", { name: /^Fler åtgärder för / })
        .first()
    ).toBeFocused();
  });
});
