import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { createSpace, openCreateCollectionDialog, uniqueName } from "./helpers";

/*
 * Decision 9: a knowledge table keeps all its columns on a touch screen and
 * scrolls sideways in its own region with the name held in view; an iPad held
 * upright shows it whole. Sort headers are 44 px targets with their arrows
 * shown (there is no hover to reveal them). On a phone a space's Kunskap tab
 * lists rows instead; a collection's files stay a table.
 */

/** A space with one website, on its Kunskap tab's websites. */
async function spaceWithWebsite(page: Page) {
  const space = await createSpace(page, uniqueName("E2E Tabeller"));
  await page.goto(`${space}/knowledge?tab=websites`);
  await page
    .getByRole("main")
    .getByRole("button", { name: /anslut webbplats|connect website/i })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/^(webbadress|web address)/i).fill("https://example.org/e2e");
  await dialog.getByRole("button", { name: /skapa webbplats|create website/i }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("main").getByRole("link", { name: /example\.org/ })).toBeVisible();
}

/** The websites table and its scroll region (from 768 px). */
async function websitesTable(page: Page) {
  await spaceWithWebsite(page);
  const table = page.getByRole("table", { name: /webbplatser|websites/i });
  return { table, region: page.getByRole("group", { name: /webbplatser|websites/i }) };
}

test.describe("knowledge tables on a touch screen narrower than they are", () => {
  // The narrowest table width (768 px): the websites table scrolls there.
  test.use({ viewport: { width: 768, height: 1024 }, hasTouch: true, isMobile: true });

  test("scroll sideways with the name in view, behind 44 px sort headers", async ({
    page,
    browserName
  }) => {
    const { table, region } = await websitesTable(page);
    await expect
      .poll(() => region.evaluate((el) => el.scrollWidth - el.clientWidth))
      .toBeGreaterThan(0);

    // Every sort header is a whole 44 px target, its label wrapped rather than
    // cut off at the column's edge, the arrows of an unsorted column shown.
    const sortHeaders = await table.locator("thead button").all();
    expect(sortHeaders.length).toBeGreaterThan(1);
    for (const button of sortHeaders) {
      const fit = await button.evaluate((el) => {
        const cell = el.closest("th")!.getBoundingClientRect();
        const label = el.firstElementChild!.getBoundingClientRect();
        const arrows = el.querySelector(":scope > span:has(> .astryx-icon)")!;
        return {
          height: el.getBoundingClientRect().height,
          labelInside: label.right <= cell.right + 0.5,
          arrows: getComputedStyle(arrows).opacity
        };
      });
      expect(fit).toEqual({ height: expect.any(Number), labelInside: true, arrows: "1" });
      expect(fit.height).toBeGreaterThanOrEqual(44);
    }

    // Scrolled to its end, the name still starts the row, on the same surface
    // as the cells it covers: no strip of another colour.
    await region.evaluate((el) => {
      el.scrollLeft = el.scrollWidth;
    });
    const pinned = await table.evaluate((el) => {
      const scroller = el.closest(".astryx-table-scroll-wrapper")!;
      const header = el.querySelector<HTMLElement>("thead th[data-column-key='name']")!;
      const cell = el.querySelector<HTMLElement>("tbody td:nth-child(2)")!;
      // The colour the rows sit on: the nearest one painted behind them.
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
        offset: Math.round(header.getBoundingClientRect().left - box.left),
        header: getComputedStyle(header).backgroundColor,
        headerRow: behind(header.parentElement!),
        cell: getComputedStyle(cell).backgroundColor,
        row: behind(cell.parentElement!)
      };
    });
    expect(pinned.scrolled).toBe(true);
    // The selection checkbox's column is held in view before the name.
    expect(pinned.offset).toBeGreaterThanOrEqual(36);
    expect(pinned.header).toBe(pinned.headerRow);
    expect(pinned.cell).toBe(pinned.row);

    // Focus on a pinned control, always in view, leaves the columns being
    // read where they are.
    const scrollLeft = () => region.evaluate((el) => el.scrollLeft);
    const readingAt = await scrollLeft();
    await table.getByRole("link", { name: /example\.org/ }).focus();
    expect(await scrollLeft()).toBe(readingAt);

    // Focus moving back to a control scrolled under the name comes to rest
    // beside the name, not hidden behind it (WCAG 2.4.11).
    await table.getByRole("button", { name: /fler åtgärder|more actions/i }).focus();
    // Safari moves Tab between links only with Option held.
    await page.keyboard.press(browserName === "webkit" ? "Alt+Shift+Tab" : "Shift+Tab");
    const link = table.getByRole("link", { name: /gå till webbplats|go to website/i });
    await expect(link).toBeFocused();
    const clear = await link.evaluate((el) => {
      const box = el.getBoundingClientRect();
      const hit = document.elementFromPoint(box.left + 4, box.top + box.height / 2);
      return hit !== null && el.contains(hit);
    });
    expect(clear).toBe(true);

    // The page itself never scrolls sideways.
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    ).toBeLessThanOrEqual(0);
  });
});

test.describe("knowledge on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("the Kunskap tab lists rows, its source chosen with a segmented control", async ({
    page
  }) => {
    await spaceWithWebsite(page);
    const sources = page.getByRole("radiogroup", { name: /kunskapskällor|knowledge sources/i });
    await expect(sources).toBeVisible();
    await expect(sources.getByRole("radio", { name: /webbplatser|websites/i })).toBeChecked();
    await expect(page.getByRole("table")).toHaveCount(0);
    const websites = page.getByRole("list", { name: /webbplatser|websites/i });
    await expect(websites.getByRole("link", { name: /example\.org/ })).toBeVisible();
    await expect(
      websites.getByRole("button", { name: /fler åtgärder för|more actions for/i })
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    ).toBeLessThanOrEqual(0);

    await sources.getByRole("radio", { name: /samlingar|collections/i }).click();
    await expect(page).toHaveURL(/[?&]tab=collections/);
  });

  test("a table that fits keeps its pinned cells on their own columns", async ({ page }) => {
    const space = await createSpace(page, uniqueName("E2E Filer"));
    await page.goto(`${space}/knowledge`);
    const create = await openCreateCollectionDialog(page);
    await create.getByLabel(/^(namn|name)$/i).fill("Bygglovsguider");
    await create.getByRole("button", { name: /skapa samling|create collection/i }).click();
    await page.waitForURL(/\/knowledge\/collections\/[^/]+$/);
    await page.getByRole("button", { name: /lägg till text|add text/i }).click();
    const dialog = page.getByRole("dialog", { name: /lägg till text|add text/i });
    await dialog.getByLabel(/^(titel|title)$/i).fill("Strandskydd.pdf");
    await dialog
      .getByLabel(/^(innehåll|content)$/i)
      .fill("Strandskyddet gäller vid alla stränder.");
    await dialog.getByRole("button", { name: /^(skicka|submit)$/i }).click();
    const table = page.getByRole("table", { name: "Bygglovsguider" });
    await expect(table.getByRole("button", { name: "Strandskydd.pdf", exact: true })).toBeVisible();

    // The files fit a phone: nothing to scroll, and every header cell starts
    // where the one before it ends (a pinned one sits on its own column).
    const layout = await table.evaluate((el) => {
      const scroller = el.closest(".astryx-table-scroll-wrapper")!;
      const cells = [...el.querySelectorAll("thead th")].map((th) => th.getBoundingClientRect());
      const box = scroller.getBoundingClientRect();
      return {
        edges: [Math.round(box.left), Math.round(innerWidth - box.right)],
        overflow: scroller.scrollWidth - scroller.clientWidth,
        starts: cells.map((box) => Math.round(box.left)),
        ends: [
          Math.round(scroller.getBoundingClientRect().left),
          ...cells.map((box) => Math.round(box.right))
        ].slice(0, -1)
      };
    });
    // Edge to edge on a phone, over the page's gutters.
    expect(layout.edges).toEqual([0, 0]);
    expect(layout.overflow).toBeLessThanOrEqual(0);
    expect(layout.starts).toEqual(layout.ends);
  });
});

test.describe("knowledge tables on an iPad held upright", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true, isMobile: true });

  test("the widest knowledge table fits without scrolling sideways", async ({ page }) => {
    const { region } = await websitesTable(page);
    expect(await region.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0);
  });
});
