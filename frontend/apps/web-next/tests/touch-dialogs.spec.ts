import type { Locator, Page } from "@playwright/test";
import { expect, test } from "./csp";
import { createSpace, uniqueName } from "./helpers";

async function openCreateSpace(page: Page) {
  await page.goto("/spaces/list");
  // Scope to the page: the SideNav has its own "Skapa yta".
  await page
    .getByRole("main")
    .getByRole("button", { name: /skapa yta|create space/i })
    .click();
  return page.getByRole("dialog");
}

/** The dialog's box once its entrance animation (a scale) has finished. */
async function settledBox(dialog: Locator) {
  await expect(dialog).toBeVisible();
  await dialog.evaluate((element) =>
    Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished))
  );
  return (await dialog.boundingBox())!;
}

test.describe("a form dialog on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("hangs from the top, so its field and buttons stay above the keyboard", async ({ page }) => {
    const dialog = await openCreateSpace(page);
    expect((await settledBox(dialog)).y).toBeLessThanOrEqual(32);

    // Required is the default and unmarked (decision 40).
    const name = dialog.getByRole("textbox", { name: "Namn", exact: true });
    await expect(name).toHaveAttribute("aria-required", "true");
    // A phone's keyboard takes about the lower 40 % of the screen.
    for (const control of [
      name,
      dialog.getByRole("button", { name: "Avbryt" }),
      dialog.getByRole("button", { name: "Skapa yta" })
    ]) {
      const box = (await control.boundingBox())!;
      expect(box.y + box.height).toBeLessThan(844 * 0.6);
    }
  });
});

test.describe("the type-the-name dialog on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("hangs from the top too", async ({ page }) => {
    const name = uniqueName("Touch delete");
    await createSpace(page, name);
    await page.goto("/spaces/list");
    // Filtered to the one row, so it sits at the top of a long seeded list.
    await page.getByRole("textbox", { name: /filtrera/i }).fill(name);
    await page.getByRole("button", { name: `Fler åtgärder för ${name}` }).click();
    await page.getByRole("menuitem", { name: "Radera yta" }).click();

    const dialog = page.getByRole("dialog", { name: "Radera yta" });
    expect((await settledBox(dialog)).y).toBeLessThanOrEqual(32);
    for (const control of [
      dialog.getByRole("textbox", { name: "Ange ytnamnet för att bekräfta" }),
      dialog.getByRole("button", { name: "Bekräfta borttagning" })
    ]) {
      const box = (await control.boundingBox())!;
      expect(box.y + box.height).toBeLessThan(844 * 0.6);
    }
  });
});

test.describe("a form dialog with a mouse", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test("stays centred", async ({ page }) => {
    const dialog = await openCreateSpace(page);
    const box = await settledBox(dialog);
    expect(Math.abs(box.y + box.height / 2 - 450)).toBeLessThan(24);
  });
});
