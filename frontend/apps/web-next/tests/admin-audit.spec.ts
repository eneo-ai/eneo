import { expect, test } from "./csp";
import { auditLogs } from "./helpers";

// One test, one access session: the backend allows five an hour.
test.describe("the audit log on a phone, then a tablet (decision 9)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("keeps every column, the event in view, opens its details; fits a tablet", async ({
    page
  }) => {
    const { table, region } = await auditLogs(page);
    await expect(table.getByRole("columnheader")).toHaveCount(4);
    await expect
      .poll(() => region.evaluate((el) => el.scrollWidth - el.clientWidth))
      .toBeGreaterThan(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390
    );
    // Scrolled to its end, the event still starts the row, at the screen's edge.
    await region.evaluate((el) => {
      el.scrollLeft = el.scrollWidth;
    });
    const offset = await table.evaluate((el) => {
      const header = el.querySelector<HTMLElement>("thead th[data-column-key='event']")!;
      return Math.round(header.getBoundingClientRect().left);
    });
    expect(offset).toBe(0);

    const event = table.getByRole("button").first();
    expect((await event.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    // Opened by a tap, closed by its close button and by Escape: focus
    // comes back to the event each time.
    const dialog = page.getByRole("dialog");
    for (const close of ["button", "Escape"] as const) {
      await event.click();
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText("Tidsstämpel")).toBeVisible();
      if (close === "button") await dialog.getByRole("button", { name: /stäng/i }).first().click();
      else await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(event).toBeFocused();
    }

    // An iPad held upright: the table fits.
    await page.setViewportSize({ width: 820, height: 1180 });
    await expect
      .poll(() => region.evaluate((el) => el.scrollWidth - el.clientWidth))
      .toBeLessThanOrEqual(0);
  });
});
