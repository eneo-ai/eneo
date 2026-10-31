import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { createSpace, productionAsset, uniqueName } from "./helpers";
import sv from "../src/lib/i18n/messages/sv.json";

// Below 1024 px a page's own header replaces the shell's top bar. These
// checks cover loaded screens and navigation when a page chunk is delayed or missing.

const PHONE = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true };
test.use(PHONE);

// The shell's top bar: a space's own header (tablets, desktop) is a <header> in main.
const TOP_BAR = "header:not(main *)";

type Frame = { top: boolean; own: boolean; h1: boolean; at: number };

/**
 * Records, every animation frame from the first byte, whether the top bar, a
 * page's own header and the page's h1 are on screen (`window.__headerFrames`).
 */
async function recordHeaders(page: Page) {
  await page.addInitScript((topBar) => {
    const frames: Frame[] = [];
    (window as unknown as { __headerFrames: Frame[] }).__headerFrames = frames;
    const shown = (element: Element | null) => !!element && element.getClientRects().length > 0;
    const start = performance.now();
    const tick = () => {
      if (document.body) {
        const frame = {
          top: shown(document.querySelector(topBar)),
          own: [...document.querySelectorAll("[data-own-mobile-header]")].some(shown),
          h1: [...document.querySelectorAll("main h1")].some(shown),
          at: Math.round(performance.now() - start)
        };
        const last = frames.at(-1);
        if (!last || last.top !== frame.top || last.own !== frame.own || last.h1 !== frame.h1) {
          frames.push(frame);
        }
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, TOP_BAR);
}

const headerFrames = (page: Page) =>
  page.evaluate(() => (window as unknown as { __headerFrames: Frame[] }).__headerFrames);

test("a loaded pushed screen or chat shows only its own header", async ({ page }) => {
  const open = (path: string) => page.goto(path);

  for (const pushed of ["/admin/users", "/account/appearance", "/spaces/personal/chat"]) {
    await open(pushed);
    await expect(page.locator("[data-own-mobile-header]")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator(TOP_BAR)).toBeHidden();
  }
  await open("/admin/users");
  await expect(
    page.getByRole("link", { name: /^(Tillbaka till|Back to) Administration$/ })
  ).toBeVisible();

  for (const root of ["/admin", "/account", "/spaces/list"]) {
    await open(root);
    // Konto is rendered with "Mitt konto" until the width is known, CSS showing one.
    await expect(page.locator("main h1").filter({ visible: true })).toBeVisible({
      timeout: 15_000
    });
    await expect(page.locator(TOP_BAR)).toBeVisible();
    await expect(page.locator("[data-own-mobile-header]")).toHaveCount(0);
  }
});

test("a shared space is pushed on a phone; the personal and organisation spaces keep the menu", async ({
  page
}) => {
  const name = uniqueName("E2E Pushed Space");
  const space = await createSpace(page, name);
  const back = page.getByRole("link", { name: /^(Tillbaka till|Back to) (Ytor|Spaces)$/ });
  const tabs = page.getByRole("navigation", { name: /^(Ytans innehåll|Space content)$/ });

  await page.goto(`${space}/overview`);
  await expect(back).toBeVisible();
  await expect(page.locator(TOP_BAR)).toBeHidden();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(tabs.getByRole("link")).toHaveCount(4);
  const strip = await tabs.evaluate((nav) => {
    const scroller = [...nav.querySelectorAll<HTMLElement>("*")].find(
      (element) => getComputedStyle(element).overflowX === "auto"
    );
    return scroller ? scroller.scrollWidth - scroller.clientWidth : 0;
  });
  expect(strip).toBeLessThanOrEqual(1);
  const manage = page.getByRole("region", { name: /^(Hantera ytan|Manage space)$/ });
  // The whole row is the link (globals.css 12b): its icon, outside the label, opens it.
  const row = manage.locator(".astryx-item").filter({ hasText: /^(Medlemmar|Members)/ });
  await row.click({ position: { x: 16, y: 28 } });
  await expect(page).toHaveURL(new RegExp(`${space}/members$`));
  await expect(
    page.getByRole("link", { name: new RegExp(`^(Tillbaka till|Back to) ${name}$`) })
  ).toBeVisible();

  for (const root of ["/spaces/personal/overview", "/spaces/organization/knowledge"]) {
    await page.goto(root);
    await expect(page.locator("main h1")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator(TOP_BAR)).toBeVisible();
    await expect(page.locator("[data-own-phone-header]")).toHaveCount(0);
  }
  await expect(tabs.getByRole("link")).toHaveCount(4);
});

test("a long space name in the back link never makes a 320 px page scroll sideways", async ({
  page
}) => {
  const name = uniqueName("E2E Rymdstyrelseförvaltningens personalavdelning och arbetsmiljöenhet");
  const space = await createSpace(page, name);
  await page.setViewportSize({ width: 320, height: 640 });
  await page.goto(`${space}/members`);
  const back = page.getByRole("link", { name: `Tillbaka till ${name}` });
  await expect(back).toBeVisible();
  const overflow = await page.evaluate(() => {
    const main = document.getElementById("main-content")!;
    return Math.max(
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
      main.scrollWidth - main.clientWidth
    );
  });
  expect(overflow).toBeLessThanOrEqual(1);
  const box = (await back.boundingBox())!;
  expect(box.x + box.width).toBeLessThanOrEqual(320);
});

test("the shell remains usable while a destination's code loads", async ({ page }) => {
  const asset = productionAsset("src/routes/_app/admin/users.tsx?tsr-split=component");
  let held = 0;
  let release!: () => void;
  const released = new Promise<void>((resolve) => (release = resolve));
  await page.route(
    (url) => url.pathname === asset,
    async (route) => {
      held++;
      await released;
      await route.continue();
    }
  );
  try {
    await page.goto("/admin");
    await page.getByRole("button", { name: /öppna menyn|open menu/i }).click();
    await page
      .getByRole("dialog", { name: /^(Meny|Menu)$/ })
      .getByRole("link", { name: /^(Användare|Users)$/ })
      .click();
    await expect.poll(() => held).toBeGreaterThan(0);

    const palette = page.getByRole("dialog", { name: /^(Sök i Eneo|Search Eneo)$/ });
    await page.keyboard.press("ControlOrMeta+k");
    await expect(palette).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(palette).toBeHidden();

    release();
    await expect(page).toHaveURL(/\/admin\/users$/);
    await expect(page.locator("[data-own-mobile-header]")).toBeVisible();
    await expect(page.locator(TOP_BAR)).toBeHidden();
    await expect(
      page.getByRole("button", { name: /^(Skapa användare|Create user)$/ })
    ).toBeVisible();
  } finally {
    release();
    await page.unrouteAll({ behavior: "ignoreErrors" });
  }
});

test("a missing page chunk shows an error and the back link still leads out", async ({ page }) => {
  const asset = productionAsset("src/routes/_app/admin/users.tsx?tsr-split=component");
  let failed = 0;
  await page.route(
    (url) => url.pathname === asset,
    async (route) => {
      failed++;
      await route.fulfill({ status: 404, body: "Missing deployed chunk" });
    }
  );
  await page.goto("/admin/users");
  await expect(page.getByRole("heading", { name: sv.something_went_wrong })).toBeVisible();
  expect(failed, "the production page chunk was actually faulted").toBeGreaterThan(0);
  await page.getByRole("link", { name: /^(Tillbaka till|Back to) Administration$/ }).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.locator("main h1")).toBeVisible();
});

test("focus moving up a pushed screen stops below its PageBar", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 480 });
  await page.goto("/admin/users");
  const barBottom = await page
    .locator("[data-page-bar]")
    .evaluate((bar) => bar.getBoundingClientRect().bottom);
  const main = page.locator("#main-content");

  // A control scrolled past, focused again (focus(), as on Shift+Tab).
  await main.evaluate((element) => (element.scrollTop = element.scrollHeight));
  const create = page.getByRole("button", { name: /^(Skapa användare|Create user)$/ });
  await create.focus();
  expect((await create.boundingBox())!.y).toBeGreaterThanOrEqual(barBottom - 1);

  // Backwards through the page from its end: never under the bar.
  await main.evaluate((element) => (element.scrollTop = element.scrollHeight));
  await page.locator("main button, main a[href], main input").last().focus();
  for (let step = 0; step < 20; step++) {
    await page.keyboard.press("Shift+Tab");
    const top = await page.evaluate(() => {
      const focused = document.activeElement;
      if (!focused || !focused.closest("#main-content") || focused.closest("[data-page-bar]")) {
        return null;
      }
      return focused.getBoundingClientRect().top;
    });
    if (top !== null) expect(top, `step ${step}`).toBeGreaterThanOrEqual(barBottom - 1);
  }
});

test("going from a root screen to a pushed one shows one header throughout", async ({ page }) => {
  await recordHeaders(page);
  await page.goto("/admin");
  await expect(page.locator(TOP_BAR)).toBeVisible();

  await page.getByRole("button", { name: /öppna menyn|open menu/i }).click();
  const drawer = page.getByRole("dialog", { name: /^(Meny|Menu)$/ });
  await drawer.getByRole("link", { name: /^(Användare|Users)$/ }).click();
  await expect(
    page.getByRole("link", { name: /^(Tillbaka till|Back to) Administration$/ })
  ).toBeVisible();
  await expect(page.locator(TOP_BAR)).toBeHidden();

  const frames = await headerFrames(page);
  const firstHeader = frames.findIndex((frame) => frame.top || frame.own);
  for (const frame of frames.slice(firstHeader)) {
    expect(frame.top !== frame.own, `one header at ${frame.at} ms`).toBe(true);
  }
});
