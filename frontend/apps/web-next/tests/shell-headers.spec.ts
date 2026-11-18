import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { createSpace, productionAsset, uniqueName } from "./helpers";
import sv from "../src/lib/i18n/messages/sv.json";

// On a phone a page's own header replaces the shell's top bar. These
// checks cover loaded screens and navigation when a page chunk is delayed or missing.

const PHONE = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true };
test.use(PHONE);

// The shell's top bar: the phone's, or a computer's; a space's own header is a <header> in main.
const TOP_BAR = "header:not(main *)";
// A page's own header: a pushed screen's (Konto, the chat) or a phone's only (a space, an admin area).
const OWN_HEADER = "[data-own-mobile-header], [data-own-phone-header]";

type Frame = { top: boolean; own: boolean; h1: boolean; at: number };

/**
 * Records, every animation frame from the first byte, whether the top bar, a
 * page's own header and the page's h1 are on screen (`window.__headerFrames`).
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
    },
    [TOP_BAR, OWN_HEADER] as const
  );
}

const headerFrames = (page: Page) =>
  page.evaluate(() => (window as unknown as { __headerFrames: Frame[] }).__headerFrames);

test("a shared space is pushed on a phone; the personal and organisation spaces keep the menu", async ({
  page
}) => {
  const name = uniqueName("E2E Pushed Space");
  const space = await createSpace(page, name);
  const back = page.getByRole("link", {
    name: /^(Tillbaka till|Back to) (Dina ytor|Your spaces)$/
  });
  const tabs = page.getByRole("navigation", { name: /^(Ytans innehåll|Space content)$/ });

  await page.goto(`${space}/overview`);
  await expect(back).toBeVisible();
  await expect(page.locator(TOP_BAR)).toBeHidden();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  // The name once: the header's h1, not again on Översikt.
  await expect(page.getByRole("heading", { name, exact: true })).toHaveCount(1);
  await expect(tabs.getByRole("link")).toHaveCount(4);
  // What to open, not count tiles that repeat the tabs above.
  await expect(page.getByRole("region", { name: /^(Assistenter|Assistants)$/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /^(Assistenter|Assistants) \d+$/ })).toHaveCount(0);
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
  // The organisation space: knowledge, skills and settings (legacy services are hidden).
  await expect(tabs.getByRole("link")).toHaveCount(3);
});

test("the menu lists the spaces, the current one marked, one tap from the others", async ({
  page
}) => {
  const name = uniqueName("E2E Drawer Space");
  const space = await createSpace(page, name);
  const drawer = page.getByRole("dialog", { name: /^(Meny|Menu)$/ });

  await page.goto("/spaces/personal/overview");
  await page.getByRole("button", { name: /^(Öppna menyn|Open menu)$/ }).click();
  await expect(drawer.getByRole("link", { name: /^(Personligt|Personal)$/ })).toHaveAttribute(
    "aria-current",
    "page"
  );
  await expect(drawer.locator('[aria-current="page"]')).toHaveCount(1);
  await expect(drawer.getByRole("link", { name: /^(Dina ytor|Your spaces)$/ })).toHaveAttribute(
    "href",
    "/spaces/list"
  );
  expect(await drawer.evaluate((element) => element.scrollWidth - element.clientWidth)).toBe(0);

  // A shared space's chat opens the menu from its own header; the space is
  // listed and marked even past the menu's first spaces.
  await page.goto(`${space}/chat`);
  await page.getByRole("button", { name: /^(Öppna menyn|Open the menu)$/ }).click();
  await expect(drawer.getByRole("link", { name, exact: true })).toHaveAttribute(
    "aria-current",
    "page"
  );
  await drawer.getByRole("link", { name: /^(Personligt|Personal)$/ }).click();
  await expect(page).toHaveURL(/\/spaces\/personal\/overview$/);
  await expect(drawer).toBeHidden();
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

test("the top bar keeps Ny konversation at 360 and 320 px, and gives it up only at large text", async ({
  page
}) => {
  await page.goto("/dashboard");
  const bar = page.getByRole("banner");
  const pen = bar.getByRole("link", { name: "Ny konversation" });
  for (const width of [360, 320]) {
    await page.setViewportSize({ width, height: 640 });
    await expect(pen).toBeVisible();
  }
  await page.evaluate(() =>
    document.documentElement.style.setProperty("font-size", "150%", "important")
  );
  await expect(pen).toBeHidden();
});

test("every admin area's back link shows Administration, whatever the area's title", async ({
  page
}) => {
  for (const area of ["/admin/users", "/admin/user-groups", "/admin/security-classifications"]) {
    await page.goto(area);
    const back = page.getByRole("link", { name: /^(Tillbaka till|Back to) Administration$/ });
    await expect(back).toBeVisible({ timeout: 15_000 });
    await expect(back).toHaveText(/^(Administration)$/);
  }
});

test("an iPad held upright shows an admin area beside the icon rail, without the phone's bars", async ({
  page
}) => {
  await page.setViewportSize({ width: 820, height: 1180 });
  await page.goto("/admin/users");
  await expect(page.locator("main h1")).toBeVisible({ timeout: 15_000 });
  // A tablet keeps the touch shell (#1328): no top bar, the SideNav carries the areas.
  await expect(page.locator(TOP_BAR)).toBeHidden();
  await expect(page.getByRole("button", { name: /^(Öppna menyn|Open menu)$/ })).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: /^(Tillbaka till|Back to) Administration$/ })
  ).toBeHidden();
  // The rail lists every area; each item is named, as its tooltip shows.
  await expect(
    page.getByRole("button", { name: /^(Fäll ut sidomenyn|Expand the side menu)$/ })
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /^(Användare|Users)$/ }).first()).toBeVisible();
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
    await expect(page.locator(OWN_HEADER)).toBeVisible();
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
    .locator("[data-phone-page-bar]")
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
      if (
        !focused ||
        !focused.closest("#main-content") ||
        focused.closest("[data-phone-page-bar]")
      ) {
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

test("the organisation space's tab strip gives way while a settings section is open", async ({
  page
}) => {
  const tabs = page.getByRole("navigation", { name: /^(Ytans innehåll|Space content)$/ });
  await page.goto("/spaces/organization/settings");
  await expect(page.locator('[data-editor-view="index"]')).toBeVisible({ timeout: 15_000 });
  await expect(tabs).toBeVisible();

  await page.goto("/spaces/organization/settings?section=models");
  await expect(page.locator('[data-editor-view="section"]')).toBeVisible({ timeout: 15_000 });
  // Computed, not the selector text: the rule must really win over the strip's own display.
  await expect(tabs).toBeHidden();
  // The page keeps its heading for a screen reader.
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
});

test("the idle job bell stays out of the way until focus shows it, and focus can come back to it", async ({
  page
}) => {
  await page.route(/\/api\/v1\/jobs\/$/, (route) => route.fulfill({ json: { items: [] } }));
  await page.goto("/dashboard");
  const slot = page.getByRole("banner").locator("[data-job-bell]");
  const bell = slot.getByRole("button", { name: "Aviseringar" });
  await expect(bell).toBeAttached();
  expect((await slot.boundingBox())!.width).toBeLessThanOrEqual(1);

  await bell.focus();
  expect((await slot.boundingBox())!.width).toBeGreaterThanOrEqual(32);
  // A dialog over it, then back: the bell is still there to come back to.
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(bell).toBeFocused();

  await bell.blur();
  expect((await slot.boundingBox())!.width).toBeLessThanOrEqual(1);

  // Focus that is not the keyboard's does not show it: a press on Search would hide it again
  // and move Search out from under that press.
  await page.locator("main#main-content").click({ position: { x: 2, y: 2 } });
  await bell.focus();
  await expect(bell).toBeFocused();
  expect((await slot.boundingBox())!.width).toBeLessThanOrEqual(1);
});

test("the job bell comes and goes without moving Search, under a press too", async ({ page }) => {
  await page.route(/\/api\/v1\/jobs\/$/, (route) => route.fulfill({ json: { items: [] } }));
  await page.goto("/dashboard");
  const banner = page.getByRole("banner");
  const bell = banner.locator("[data-job-bell]").getByRole("button", { name: "Aviseringar" });
  const search = banner.getByRole("button", { name: "Sök" });
  await expect(search).toBeVisible();
  const idle = (await search.boundingBox())!;

  await bell.focus();
  await expect(bell).toBeFocused();
  expect((await search.boundingBox())!.x).toBe(idle.x);

  await page.mouse.move(idle.x + idle.width / 2, idle.y + idle.height / 2);
  await page.mouse.down();
  // Within a pixel: a pressed button dips.
  expect(Math.abs((await search.boundingBox())!.x - idle.x)).toBeLessThan(1);
  await page.mouse.up();
  await expect(page.getByRole("dialog", { name: /^(Sök i Eneo|Search Eneo)$/ })).toBeVisible();
});
