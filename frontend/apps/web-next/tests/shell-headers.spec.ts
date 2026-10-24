import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { createSpace, uniqueName } from "./helpers";

// Below 1024 px a page with its own header (the chat's, a pushed screen's
// PageBar) replaces the shell's top bar. The top bar gives way in CSS
// (app-shell.tsx, OWN_MOBILE_HEADER), so this has to hold before any script
// runs, while the page's code is still loading and across client navigation:
// one header on screen, never two, and the server-rendered page never swapped
// for its loading state.

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

test("before hydration, a pushed screen or a chat shows only its own header", async ({ page }) => {
  // The app's code never arrives; Next's inline scripts still move the
  // streamed page into place, as they do before hydration. (With scripts off
  // altogether the streamed page would never leave its hidden template.)
  await page.route(
    (url) => url.pathname.startsWith("/_next/static/chunks/") && url.pathname.endsWith(".js"),
    (route) => route.abort()
  );
  const open = (path: string) => page.mainFrame().goto(path);

  for (const pushed of ["/admin/users", "/spaces/personal/chat"]) {
    await open(pushed);
    // The dev server may compile the route first.
    await expect(page.locator("[data-own-mobile-header]")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator(TOP_BAR)).toBeHidden();
  }
  await open("/admin/users");
  await expect(
    page.getByRole("link", { name: /^(Tillbaka till|Back to) Administration$/ })
  ).toBeVisible();

  for (const root of ["/admin", "/spaces/list"]) {
    await open(root);
    await expect(page.locator("main h1")).toBeVisible({ timeout: 15_000 });
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

  // Before any script runs (decision 24): the space's bar, not the menu.
  await page.route(isChunk, (route) => route.abort());
  await page.mainFrame().goto(`${space}/overview`);
  await expect(page.locator("[data-own-phone-header]")).toBeVisible({ timeout: 15_000 });
  await expect(back).toBeVisible();
  await expect(page.locator(TOP_BAR)).toBeHidden();
  await page.unrouteAll({ behavior: "ignoreErrors" });

  // Hydrated: the content tabs fit without scrolling, the rest is under Hantera ytan.
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
  await manage.getByRole("link", { name: /^(Medlemmar|Members)/ }).click();
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

/** Script chunks of the app (not Next's inline streaming scripts). */
const isChunk = (url: URL) =>
  url.pathname.startsWith("/_next/static/chunks/") && url.pathname.endsWith(".js");
/** A string only the users page's code holds (its tabs' label key). */
const USERS_PAGE_CODE = "admin_users_tabs_label";
/** A string of the shell's code: it must never be held with the page. */
const SHELL_CODE = "group/shell";

const isHydrated = (page: Page, selector: string) =>
  page
    .locator(selector)
    .first()
    .evaluate((element) => Object.keys(element).some((key) => key.startsWith("__reactFiber$")));

test("the shell answers while a pushed screen's code loads, and the server page stays", async ({
  page
}) => {
  // Hold the users page's code only: the shell hydrates, the page cannot.
  const held: string[] = [];
  let release!: () => void;
  const released = new Promise<void>((resolve) => (release = resolve));
  await page.route(isChunk, async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    if (body.includes(USERS_PAGE_CODE)) {
      held.push(body.includes(SHELL_CODE) ? "page and shell" : "page");
      await released;
    }
    await route.fulfill({ response, body });
  });
  await recordHeaders(page);
  // Not page.goto: the csp fixture's goto waits for the page to hydrate.
  await page.mainFrame().goto("/admin/users", { waitUntil: "commit" });
  await expect(page.locator("main h1")).toBeVisible({ timeout: 15_000 });
  await expect.poll(() => held.length).toBeGreaterThan(0);
  expect(
    held.every((code) => code === "page"),
    "the shell's code is never held"
  ).toBe(true);

  // The shell is live: ⌘K opens its palette and Escape closes it.
  const palette = page.getByRole("dialog", { name: /^(Sök i Eneo|Search Eneo)$/ });
  await expect(async () => {
    await page.keyboard.press("ControlOrMeta+k");
    await expect(palette).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 15_000 });
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();

  // Meanwhile the page is still the server's, not swapped for its loading state.
  expect(await isHydrated(page, "main h1")).toBe(false);
  await expect(page.locator("[data-own-mobile-header]")).toBeVisible();
  await expect(page.locator(TOP_BAR)).toBeHidden();

  release();
  await expect.poll(() => isHydrated(page, "main h1"), { timeout: 15_000 }).toBe(true);

  // From the first frame with the page in it: the page stays, under one header.
  const frames = await headerFrames(page);
  const firstPage = frames.findIndex((frame) => frame.h1);
  expect(firstPage).toBeGreaterThanOrEqual(0);
  for (const frame of frames.slice(firstPage)) {
    expect(frame, `at ${frame.at} ms`).toMatchObject({ top: false, own: true, h1: true });
  }
});

test("when a pushed screen's code fails to load, its server-rendered back link still leads out", async ({
  page
}) => {
  await page.route(isChunk, async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    if (body.includes(USERS_PAGE_CODE)) return route.abort();
    await route.fulfill({ response, body });
  });
  await page.mainFrame().goto("/admin/users", { waitUntil: "commit" });
  // React leaves the page as the server rendered it: readable, with its bar
  // (whose code is the shell's, so the link works either way).
  await expect(page.locator("main h1")).toBeVisible({ timeout: 15_000 });
  const back = page.getByRole("link", { name: /^(Tillbaka till|Back to) Administration$/ });
  await expect(back).toBeVisible();
  // It leads out without the page's code, to a screen with the menu.
  await back.click();
  await expect(page).toHaveURL(/\/admin$/);
  await page.getByRole("button", { name: /öppna menyn|open menu/i }).click();
  await expect(page.getByRole("dialog", { name: /^(Meny|Menu)$/ })).toBeVisible();
  // Chunks still on their way through the route would fail the next test.
  await page.unrouteAll({ behavior: "ignoreErrors" });
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
