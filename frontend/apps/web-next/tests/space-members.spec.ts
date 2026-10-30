import { expect, test } from "./csp";
import { createSpace, uniqueName } from "./helpers";

/*
 * Decision 25: on a phone a space's members are rows by role, and adding a
 * member or a group is docked at the bottom. The e2e stack has one user, so
 * the space shows only your own row, which opens no role sheet.
 */
test.describe("members on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("lists you as a row and docks adding members", { tag: "@vite" }, async ({ page }) => {
    const space = await createSpace(page, uniqueName("E2E Medlemmar"));
    await page.goto(`${space}/members`);

    const admins = page.getByRole("list", {
      name: /^(administratörer & redigerare|admins & editors)/i
    });
    const self = admins.getByRole("listitem").filter({ hasText: /\((du|you)\)/ });
    await expect(self).toBeVisible();
    await expect(self.getByRole("button")).toHaveCount(0);
    await expect(page.getByRole("combobox")).toHaveCount(0);

    const dock = page.getByRole("group", { name: /medlemmar, åtgärder|members, actions/i });
    await expect(dock.getByRole("button", { name: /lägg till grupp|add group/i })).toBeVisible();
    const add = dock.getByRole("button", { name: /lägg till medlem|add member/i });
    await expect(add).toBeVisible();
    expect(
      await dock.evaluate((el) => Math.round(innerHeight - el.getBoundingClientRect().bottom))
    ).toBe(0);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    ).toBeLessThanOrEqual(0);

    await add.click();
    await expect(page.getByRole("dialog", { name: /lägg till medlem|add member/i })).toBeVisible();
  });
});
