import { expect, test, type Page } from "@playwright/test";

// The shared page header (Page/Header + Page/Tabbar + Page/Title) once positioned the
// tab strip outside the flow and centred it across the header. On pages with long
// Swedish labels the strip painted over the page description, and the labels wrapped
// to a second line inside a row that is only tall enough for one. Flow settings has
// the longest labels in the app, so it is the page that shows the regression first.
const LONGEST_LABEL_PAGE = "/admin/flow-settings";

async function headerGeometry(page: Page) {
  return page.evaluate(() => {
    const header = document.querySelector<HTMLElement>(".header");
    if (!header) throw new Error("page header not rendered");
    const strip = header.querySelector<HTMLElement>('[role="tablist"]');
    if (!strip) throw new Error("tab strip not rendered");
    const heading = header.querySelector<HTMLElement>("h1");
    if (!heading) throw new Error("page title not rendered");

    const description = heading.parentElement?.querySelector<HTMLElement>("p") ?? null;
    const headerBox = header.getBoundingClientRect();
    const stripBox = strip.getBoundingClientRect();
    const titleTextRight = Math.max(
      heading.getBoundingClientRect().right,
      description?.getBoundingClientRect().right ?? 0
    );

    const tabs = Array.from(strip.querySelectorAll<HTMLElement>('[role="tab"]'));
    const rows = new Set(tabs.map((tab) => Math.round(tab.getBoundingClientRect().top)));
    const tallestTab = Math.max(...tabs.map((tab) => tab.getBoundingClientRect().height));
    const lineHeight = parseFloat(getComputedStyle(tabs[0]).lineHeight) || 20;

    return {
      tabCount: tabs.length,
      // how far the strip reaches back over the title and description text
      overlapPx: Math.round(
        Math.max(
          0,
          Math.min(titleTextRight, stripBox.right) - Math.max(headerBox.left, stripBox.left)
        )
      ),
      rowsOfTabs: rows.size,
      tallestTabPx: Math.round(tallestTab),
      singleLineLimitPx: Math.round(lineHeight * 1.9),
      spillPx: Math.round(Math.max(0, stripBox.right - headerBox.right)),
      headerHeightPx: Math.round(headerBox.height)
    };
  });
}

test("tab strip shares the header row instead of covering the title", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(LONGEST_LABEL_PAGE);
  await page.getByRole("tab").first().waitFor();

  const geometry = await headerGeometry(page);

  expect(geometry.tabCount).toBeGreaterThan(1);
  expect(geometry.overlapPx, "tab strip must not reach back over the title text").toBe(0);
  expect(geometry.rowsOfTabs, "tabs must stay on one row").toBe(1);
  expect(
    geometry.tallestTabPx,
    "a label wrapping inside its own tab makes the tab taller than one line"
  ).toBeLessThan(geometry.singleLineLimitPx);
  expect(geometry.spillPx, "the strip must stay inside the header").toBe(0);
});

test("a tab reached by keyboard stays visible once the strip scrolls", async ({ page }) => {
  // narrow enough that the longest labels cannot fit, so the strip has to scroll
  await page.setViewportSize({ width: 820, height: 800 });
  await page.goto(LONGEST_LABEL_PAGE);
  await page.getByRole("tab").first().waitFor();

  const scrollState = await page.evaluate(() => {
    const strip = document.querySelector<HTMLElement>('[role="tablist"]')!;
    const port = strip.parentElement!;
    const headerBox = document.querySelector<HTMLElement>(".header")!.getBoundingClientRect();
    return {
      overflowPx: port.scrollWidth - port.clientWidth,
      portSpillPx: Math.round(Math.max(0, port.getBoundingClientRect().right - headerBox.right))
    };
  });
  expect(scrollState.overflowPx, "expected the strip to overflow at this width").toBeGreaterThan(0);
  expect(scrollState.portSpillPx, "an overflowing strip must clip, not spill").toBe(0);

  const tabs = await page.getByRole("tab").all();
  await tabs[0].focus();
  for (let step = 1; step < tabs.length; step++) {
    await page.keyboard.press("ArrowRight");
  }

  const focused = await page.evaluate(() => {
    const strip = document.querySelector<HTMLElement>('[role="tablist"]')!;
    const port = strip.parentElement!;
    const active = document.activeElement as HTMLElement | null;
    if (!active || active.getAttribute("role") !== "tab") return null;
    const tabBox = active.getBoundingClientRect();
    const portBox = port.getBoundingClientRect();
    return {
      insidePort: tabBox.left >= portBox.left - 1 && tabBox.right <= portBox.right + 1
    };
  });

  expect(focused, "arrow keys must move focus between tabs").not.toBeNull();
  expect(focused!.insidePort, "the focused tab must be scrolled into the visible strip").toBe(true);
});

test("a tab selected by page state is revealed once the strip scrolls", async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 800 });
  await page.goto(LONGEST_LABEL_PAGE);
  await page.getByRole("tab").first().waitFor();

  // the tab a deep link selects, far enough along the strip to start out clipped
  const lastTabValue = await page.evaluate(() => {
    const tabs = Array.from(document.querySelectorAll<HTMLElement>('[role="tab"]'));
    return tabs[tabs.length - 1].getAttribute("data-value");
  });
  expect(lastTabValue, "tab triggers must expose their value").toBeTruthy();

  // selection driven by page state, not by the pointer or the keyboard
  await page.goto(`${LONGEST_LABEL_PAGE}?tab=${lastTabValue}`);
  await page.getByRole("tab").first().waitFor();

  // the reveal lands once the strip has hydrated and settled at its final width
  await expect(async () => {
    const selected = await page.evaluate(() => {
      const strip = document.querySelector<HTMLElement>('[role="tablist"]')!;
      const port = strip.parentElement!;
      const active = strip.querySelector<HTMLElement>('[data-state="active"]');
      if (!active) return null;
      const tabs = Array.from(strip.querySelectorAll<HTMLElement>('[role="tab"]'));
      const activeBox = active.getBoundingClientRect();
      const portBox = port.getBoundingClientRect();
      return {
        activeIsLast: active === tabs[tabs.length - 1],
        overflowPx: port.scrollWidth - port.clientWidth,
        insidePort: activeBox.left >= portBox.left - 1 && activeBox.right <= portBox.right + 1
      };
    });

    expect(selected, "the deep-linked tab must become the active tab").not.toBeNull();
    expect(selected!.activeIsLast).toBe(true);
    expect(selected!.overflowPx, "expected the strip to overflow at this width").toBeGreaterThan(0);
    expect(selected!.insidePort, "the active tab must be scrolled into view").toBe(true);
  }).toPass({ timeout: 10_000 });

  // and it stays revealed when the row is measured again at a different width
  await page.evaluate(() => document.fonts.ready);
  await page.setViewportSize({ width: 900, height: 800 });

  await expect
    .poll(
      async () =>
        page.evaluate(() => {
          const strip = document.querySelector<HTMLElement>('[role="tablist"]')!;
          const port = strip.parentElement!;
          const active = strip.querySelector<HTMLElement>('[data-state="active"]')!;
          const activeBox = active.getBoundingClientRect();
          const portBox = port.getBoundingClientRect();
          return activeBox.left >= portBox.left - 1 && activeBox.right <= portBox.right + 1;
        }),
      { timeout: 5_000 }
    )
    .toBe(true);
});
