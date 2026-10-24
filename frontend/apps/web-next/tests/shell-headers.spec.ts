import type { Page } from "@playwright/test";
import { expect, test } from "./csp";

// Below 1024 px a page with its own header (the chat's, a pushed screen's
// PageBar) replaces the shell's top bar. The top bar gives way in CSS
// (app-shell.tsx, OWN_MOBILE_HEADER), so this has to hold before any script
// runs, while the page's code is still loading and across client navigation:
// one header on screen, never two, and the server-rendered page never swapped
// for its loading state.

const PHONE = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true };
test.use(PHONE);

const TOP_BAR = "body header";

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

test("a pushed screen keeps its server-rendered page and header while its code loads", async ({
  page
}) => {
  // Hold the code of the admin area's PageBar (the admin layout's client
  // code): the shell hydrates first, the page waits for it.
  let heldChunks = 0;
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route(
    (url) => url.pathname.startsWith("/_next/static/chunks/") && url.pathname.endsWith(".js"),
    async (route) => {
      const response = await route.fetch();
      const body = await response.text();
      if (body.includes("shell_back_to")) {
        heldChunks += 1;
        await held;
      }
      await route.fulfill({ response, body });
    }
  );
  await recordHeaders(page);
  // Not page.goto: the csp fixture's goto waits for the page to hydrate.
  await page.mainFrame().goto("/admin/users", { waitUntil: "commit" });
  await expect(page.locator(TOP_BAR)).toBeHidden();
  await page.waitForTimeout(1500);
  expect(heldChunks, "the PageBar's code was held").toBeGreaterThan(0);
  release();
  await expect(
    page.getByRole("link", { name: /^(Tillbaka till|Back to) Administration$/ })
  ).toBeVisible();
  await page.waitForTimeout(500);

  // From the first frame with the page in it: the page stays, under one header.
  const frames = await headerFrames(page);
  const firstPage = frames.findIndex((frame) => frame.h1);
  expect(firstPage).toBeGreaterThanOrEqual(0);
  for (const frame of frames.slice(firstPage)) {
    expect(frame, `at ${frame.at} ms`).toMatchObject({ top: false, own: true, h1: true });
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
