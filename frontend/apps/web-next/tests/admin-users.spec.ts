import { expect, test } from "./csp";

test.describe("the admin users table on a phone (decision 9)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("keeps every column, scrolls in its own region with the name in view", async ({ page }) => {
    await page.goto("/admin/users");
    const table = page.getByRole("table", { name: "Aktiva användare" });
    const region = page.getByRole("group", { name: "Aktiva användare" });
    await expect(table).toBeVisible();
    await expect(table.getByRole("columnheader")).toHaveCount(4);
    await expect
      .poll(() => region.evaluate((el) => el.scrollWidth - el.clientWidth))
      .toBeGreaterThan(0);
    // The page itself does not scroll sideways: only the table's region.
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390
    );

    // Edge to edge over the 16 px gutter, and scrolled to its end, the name
    // still starts each row, on the same surface as the cells it covers.
    await region.evaluate((el) => {
      el.scrollLeft = el.scrollWidth;
    });
    const pinned = await table.evaluate((el) => {
      const scroller = el.closest(".astryx-table-scroll-wrapper")!;
      const header = el.querySelector<HTMLElement>("thead th[data-column-key='name']")!;
      const cell = el.querySelector<HTMLElement>("tbody td")!;
      const behind = (from: Element) => {
        for (let node: Element | null = from; node; node = node.parentElement) {
          const colour = getComputedStyle(node).backgroundColor;
          if (colour !== "rgba(0, 0, 0, 0)") return colour;
        }
        return null;
      };
      const box = scroller.getBoundingClientRect();
      return {
        scrolled: scroller.scrollLeft > 0,
        frameLeft: Math.round(box.left),
        offset: Math.round(header.getBoundingClientRect().left - box.left),
        cell: getComputedStyle(cell).backgroundColor,
        row: behind(cell.parentElement!)
      };
    });
    expect(pinned).toEqual({
      scrolled: true,
      frameLeft: 0,
      offset: 0,
      cell: pinned.row,
      row: expect.any(String)
    });
    // The row menu is a 44 px target once scrolled into view.
    const menu = table.getByRole("button", { name: /^Fler åtgärder för / }).first();
    await menu.scrollIntoViewIfNeeded();
    expect((await menu.boundingBox())!.height).toBeGreaterThanOrEqual(44);
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
