import type { Page } from "@playwright/test";
import { expect, test } from "./csp";

// On a phone a page with its own header (the chat's, a pushed screen's
// PageBar) replaces the shell's top bar, which gives way to it in CSS. The
// SPA has no server HTML: the page's code decides what the first frame holds.
// So the rule is about frames, not about what arrives before a script runs:
// once the page panel is on screen it carries the header the screen ends up
// with, and a frame never shows two headers or none while the page changes.

const PHONE = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true };
test.use(PHONE);

// The shell's top bar: a space's own header (tablets, desktop) is a <header> in main.
const TOP_BAR = "header:not(main *)";
// A page's own header: a pushed screen's (Konto, the chat) or a phone's only (an admin area).
const OWN_HEADER = "[data-own-mobile-header], [data-own-phone-header]";

type Frame = { top: boolean; own: boolean; h1: boolean; main: boolean; at: number };

/**
 * Records, every animation frame from the first byte, whether the top bar, a
 * page's own header, the page's h1 and the page panel are on screen
 * (`window.__headerFrames`); a frame is kept when any of them changes.
 */
async function recordHeaders(page: Page) {
  await page.addInitScript(
    ([topBar, ownHeader]) => {
      const frames: Frame[] = [];
      (window as unknown as { __headerFrames: Frame[] }).__headerFrames = frames;
      const shown = (element: Element | null) => !!element && element.getClientRects().length > 0;
      const start = performance.now();
      const tick = () => {
        if (document.body) {
          const frame = {
            top: shown(document.querySelector(topBar)),
            own: [...document.querySelectorAll(ownHeader)].some(shown),
            h1: [...document.querySelectorAll("main h1")].some(shown),
            main: shown(document.querySelector("main#main-content")),
            at: Math.round(performance.now() - start)
          };
          const last = frames.at(-1);
          if (
            !last ||
            last.top !== frame.top ||
            last.own !== frame.own ||
            last.h1 !== frame.h1 ||
            last.main !== frame.main
          ) {
            frames.push(frame);
          }
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    },
    [TOP_BAR, OWN_HEADER] as const
  );
}

const headerFrames = (page: Page) =>
  page.evaluate(() => (window as unknown as { __headerFrames: Frame[] }).__headerFrames);

const clearFrames = (page: Page) =>
  page.evaluate(() => {
    (window as unknown as { __headerFrames: Frame[] }).__headerFrames.length = 0;
  });

/** The frames from the first one with the page panel on screen. */
const withPanel = (frames: Frame[]) => {
  const first = frames.findIndex((frame) => frame.main);
  return first < 0 ? [] : frames.slice(first);
};

/** Frames showing two headers or none, in the panel's life. */
const notOneHeader = (frames: Frame[]) =>
  withPanel(frames).filter((frame) => frame.main && frame.top === frame.own);

/** How often the header on screen changed from the top bar to a page's own, or back. */
const headerSwaps = (frames: Frame[]) =>
  withPanel(frames).filter(
    (frame, index, all) =>
      index > 0 && frame.top !== all[index - 1]!.top && frame.own !== all[index - 1]!.own
  ).length;

const isAsset = (url: URL) => url.pathname.startsWith("/assets/") && url.pathname.endsWith(".js");
/** The message catalogues hold every key; the page's own code is the other match. */
const isCatalogue = (url: URL) => /\/(en|sv)-[^/]*\.js$/.test(url.pathname);
/** A string only the users page's code holds (its tabs' label key). */
const USERS_PAGE_CODE = "admin_users_tabs_label";

/** Holds the users page's code until the returned `release` is called. */
async function holdUsersPage(page: Page) {
  let release!: () => void;
  const released = new Promise<void>((resolve) => (release = resolve));
  let held = 0;
  await page.route(isAsset, async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    if (!isCatalogue(new URL(route.request().url())) && body.includes(USERS_PAGE_CODE)) {
      held++;
      await released;
    }
    await route.fulfill({ response, body });
  });
  return { release, held: () => held };
}

const openMenuLink = async (page: Page, name: RegExp) => {
  await page.getByRole("button", { name: /öppna menyn|open menu/i }).click();
  await page
    .getByRole("dialog", { name: /^(Meny|Menu)$/ })
    .getByRole("link", { name })
    .click();
};

test.describe("what the detector counts", () => {
  const frame = (top: boolean, own: boolean, at: number): Frame => ({
    top,
    own,
    h1: true,
    main: true,
    at
  });

  test("a top bar replaced by a page's own header is a swap, two headers or none is not one", () => {
    const swapped = [frame(true, false, 0), frame(true, false, 600), frame(false, true, 1800)];
    expect(headerSwaps(swapped)).toBe(1);
    expect(notOneHeader(swapped)).toEqual([]);
    expect(notOneHeader([frame(true, true, 0)])).toHaveLength(1);
    expect(notOneHeader([frame(false, false, 0)])).toHaveLength(1);
    expect(headerSwaps([frame(false, true, 0), frame(false, true, 50)])).toBe(0);
    // Before the panel exists nothing counts: a blank page is not a missing header.
    expect(
      withPanel([{ ...frame(false, false, 0), main: false }, frame(false, true, 40)])
    ).toHaveLength(1);
  });
});

const COLD = [
  ["/admin/users", "own"],
  ["/account/appearance", "own"],
  ["/spaces/personal/chat", "own"],
  ["/admin", "top"],
  ["/account", "top"],
  ["/spaces/list", "top"]
] as const;

test.describe("a screen opened cold", () => {
  for (const [path, header] of COLD) {
    test(`${path} appears with ${header === "own" ? "its own header" : "the top bar"}, from its first frame`, async ({
      page
    }) => {
      await recordHeaders(page);
      await page.mainFrame().goto(path, { waitUntil: "commit" });
      await expect(page.locator(header === "own" ? OWN_HEADER : TOP_BAR)).toBeVisible({
        timeout: 15_000
      });
      if (header === "top")
        await expect(page.locator("main h1").filter({ visible: true })).toBeVisible();
      await page.waitForTimeout(300);

      const frames = withPanel(await headerFrames(page));
      expect(frames.length, "the page panel was on screen").toBeGreaterThan(0);
      for (const frame of frames) {
        // Every recorded frame in the message, so a rare failure shows what came before and after.
        expect(frame, `at ${frame.at} ms of ${JSON.stringify(frames)}`).toMatchObject(
          header === "own" ? { top: false, own: true } : { top: true, own: false }
        );
      }
    });
  }

  test("a pushed screen whose code arrives late is not shown before it, nor under the wrong header", async ({
    page
  }) => {
    const hold = await holdUsersPage(page);
    await recordHeaders(page);
    await page.mainFrame().goto("/admin/users", { waitUntil: "commit" });
    await expect.poll(hold.held, { timeout: 15_000 }).toBeGreaterThan(0);
    // The page's code is still on its way: no panel with a header it will not keep.
    await page.waitForTimeout(500);
    expect(withPanel(await headerFrames(page)).filter((frame) => frame.top)).toEqual([]);

    hold.release();
    await expect(page.locator(OWN_HEADER)).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(300);
    const frames = withPanel(await headerFrames(page));
    expect(frames.length).toBeGreaterThan(0);
    for (const frame of frames) {
      expect(frame, `at ${frame.at} ms`).toMatchObject({ top: false, own: true });
    }
  });
});

test.describe("moving between a root screen and a pushed one", () => {
  test("one header is on screen in every frame, in both directions", async ({ page }) => {
    await recordHeaders(page);
    await page.goto("/admin");
    await expect(page.locator(TOP_BAR)).toBeVisible();
    await clearFrames(page);

    await openMenuLink(page, /^(Användare|Users)$/);
    await expect(page.locator(OWN_HEADER)).toBeVisible();
    await expect(page.locator(TOP_BAR)).toBeHidden();
    await page.getByRole("link", { name: /^(Tillbaka till|Back to) Administration$/ }).click();
    await expect(page).toHaveURL(/\/admin$/);
    await expect(page.locator(TOP_BAR)).toBeVisible();
    await page.waitForTimeout(300);

    const frames = await headerFrames(page);
    expect(notOneHeader(frames)).toEqual([]);
    expect(
      frames.some((frame) => frame.own),
      "the pushed screen was on screen"
    ).toBe(true);
  });

  test("a slow pushed screen never leaves two headers or none while it loads", async ({ page }) => {
    await recordHeaders(page);
    await page.goto("/admin");
    await expect(page.locator(TOP_BAR)).toBeVisible();
    await clearFrames(page);

    const hold = await holdUsersPage(page);
    await openMenuLink(page, /^(Användare|Users)$/);
    await expect.poll(hold.held, { timeout: 15_000 }).toBeGreaterThan(0);
    // Past the pending delay: the loading state has replaced the root screen.
    await expect(page.locator('main [aria-busy="true"]')).toBeVisible({ timeout: 5_000 });
    hold.release();
    await expect(page.locator(OWN_HEADER)).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(300);

    expect(notOneHeader(await headerFrames(page))).toEqual([]);
  });

  // Measured on 7b40894d5 at 390x844 with the users page held 1.5 s and 6 s:
  // 196 ms after the URL changes the loading state replaces the root screen
  // under the top bar, which stays for the whole wait; then the pushed
  // screen's own header replaces it.
  // A pushed destination needs its header (a bar of the same height, the
  // back link still loading) while it loads. Owner: the route files (Beads
  // eneo-web-next-vite-ded5.8.5).
  test.fixme("a slow pushed screen keeps its destination's header while it loads", async ({
    page
  }) => {
    await recordHeaders(page);
    await page.goto("/admin");
    await expect(page.locator(TOP_BAR)).toBeVisible();
    await clearFrames(page);

    const hold = await holdUsersPage(page);
    await openMenuLink(page, /^(Användare|Users)$/);
    await expect.poll(hold.held, { timeout: 15_000 }).toBeGreaterThan(0);
    await expect(page.locator('main [aria-busy="true"]')).toBeVisible({ timeout: 5_000 });
    hold.release();
    await expect(page.locator(OWN_HEADER)).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(300);

    const frames = await headerFrames(page);
    expect(headerSwaps(frames), "the header changed once the page arrived").toBe(0);
  });
});
