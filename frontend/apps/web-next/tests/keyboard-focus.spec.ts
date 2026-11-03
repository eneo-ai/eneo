import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";
import { createFixtures, openRoute, walkTags, watchDocument } from "./responsive-fixtures";
import { ROUTES } from "./responsive-routes";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

/*
 * Keyboard on every screen of tests/responsive-routes.ts, on a laptop-sized
 * window: the first Tab lands on the skip link of a signed-in screen (2.4.1),
 * and each of the next 30 stops draws something (2.4.7): a stop whose
 * surroundings look the same focused and blurred has no visible focus. It does
 * not judge how visible, only that it is there; axe cannot see this, since a
 * ring that is styled away is valid CSS. A field is judged by its frame (the
 * ring is on that, not on the <input>), a list row's link by its row.
 *
 * On a phone and an iPad it also checks that what has focus is not entirely
 * hidden by something fixed or sticky (2.4.11): the page bar, the docked action
 * bar, the composer, a toast. The browser scrolls a focused element into view;
 * the page's scroll padding has to keep it clear of those bars.
 *
 * KEYBOARD_ROUTES narrows a run to routes matching a regular expression.
 */

const STOPS = 30;
const PAD = 6;
const VIEWPORT = { width: 1280, height: 800 };
const only = process.env.KEYBOARD_ROUTES ? new RegExp(process.env.KEYBOARD_ROUTES) : null;

test(
  "every screen starts at the skip link and draws its keyboard focus",
  { tag: walkTags("@keyboard", "desktop") },
  async ({ browser, baseURL }) => {
    test.setTimeout(15 * 60_000);
    const fixtures = await createFixtures(browser, baseURL, "Focus");
    const contexts = {
      in: await browser.newContext({ baseURL, storageState: STORAGE_STATE, viewport: VIEWPORT }),
      out: await browser.newContext({
        baseURL,
        storageState: { cookies: [], origins: [] },
        viewport: VIEWPORT
      })
    };
    const pages = { in: await contexts.in.newPage(), out: await contexts.out.newPage() };
    const watch = { in: watchDocument(pages.in), out: watchDocument(pages.out) };
    const problems: string[] = [];

    for (const [pattern, entry] of Object.entries(ROUTES)) {
      if ("skip" in entry || (only && !only.test(pattern))) continue;
      const signedIn = entry.auth !== "out";
      const page = pages[signedIn ? "in" : "out"];
      try {
        await openRoute(page, entry.url(fixtures), signedIn);
      } catch (error) {
        problems.push(`${pattern}: did not open (${String(error).split("\n")[0]})`);
        continue;
      }
      watch[signedIn ? "in" : "out"].begin(pattern);
      try {
        await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.());

        for (let stop = 0; stop < STOPS; stop++) {
          await page.keyboard.press("Tab");
          const focused = await page.evaluate(() => {
            const element = document.activeElement as HTMLElement | null;
            if (!element || element === document.body) return null;
            const frame =
              element.closest(
                "label, .astryx-item, [class*='text-input'], [class*='textarea'], [class*='combobox'], [class*='select']"
              ) ?? element;
            const box = frame.getBoundingClientRect();
            const name = (element.getAttribute("aria-label") || element.textContent || "")
              .trim()
              .replace(/\s+/g, " ")
              .slice(0, 28);
            return { name: `${element.tagName.toLowerCase()}:${name}`, box };
          });
          if (!focused) continue;
          if (stop === 0 && signedIn && !/Hoppa till innehåll|Skip to/i.test(focused.name)) {
            problems.push(`${pattern}: the first Tab stop is ${focused.name}, not the skip link`);
          }
          const { x, y, width, height } = focused.box;
          const left = Math.max(0, x - PAD);
          const top = Math.max(0, y - PAD);
          const clip = {
            x: left,
            y: top,
            width: Math.min(VIEWPORT.width - left, width + PAD * 2),
            height: Math.min(VIEWPORT.height - top, height + PAD * 2)
          };
          // Off screen, or too small to compare: not judged.
          if (width < 2 || height < 2 || clip.width < 4 || clip.height < 4 || y > VIEWPORT.height)
            continue;
          const withFocus = await page.screenshot({ clip });
          await page.evaluate(() => (document.activeElement as HTMLElement).blur());
          const without = await page.screenshot({ clip });
          if (withFocus.equals(without))
            problems.push(`${pattern}: no visible focus on ${focused.name}`);
          // Back where the keyboard was, so the next Tab continues from it.
          await page.keyboard.press("Shift+Tab");
          await page.keyboard.press("Tab");
        }
      } catch (error) {
        throw watch[signedIn ? "in" : "out"].explain(error);
      }
    }
    for (const context of Object.values(contexts)) await context.close();
    expect(problems, problems.join("\n")).toEqual([]);
  }
);

const TOUCH_SIZES = [
  { name: "phone", width: 390, height: 844 },
  // A phone turned: the browser's own bars leave about 300 px, so a fixed bar covers most of it.
  { name: "phone held sideways", width: 667, height: 300 },
  { name: "ipad", width: 820, height: 1180 },
  { name: "ipad held sideways", width: 1180, height: 820 }
] as const;

for (const size of TOUCH_SIZES) {
  test(
    `keyboard focus is not hidden by a fixed or sticky bar on a ${size.name}`,
    { tag: walkTags("@keyboard", size.name) },
    async ({ browser, baseURL }) => {
      test.setTimeout(15 * 60_000);
      const fixtures = await createFixtures(browser, baseURL, "Obscured");
      const contexts = {
        in: await browser.newContext({
          baseURL,
          storageState: STORAGE_STATE,
          viewport: { width: size.width, height: size.height },
          hasTouch: true,
          isMobile: true
        }),
        out: await browser.newContext({
          baseURL,
          storageState: { cookies: [], origins: [] },
          viewport: { width: size.width, height: size.height },
          hasTouch: true,
          isMobile: true
        })
      };
      const pages = { in: await contexts.in.newPage(), out: await contexts.out.newPage() };
      const watch = { in: watchDocument(pages.in), out: watchDocument(pages.out) };
      const problems: string[] = [];

      for (const [pattern, entry] of Object.entries(ROUTES)) {
        if ("skip" in entry || (only && !only.test(pattern))) continue;
        const signedIn = entry.auth !== "out";
        const page = pages[signedIn ? "in" : "out"];
        try {
          await openRoute(page, entry.url(fixtures), signedIn);
        } catch (error) {
          problems.push(`${pattern}: did not open (${String(error).split("\n")[0]})`);
          continue;
        }
        watch[signedIn ? "in" : "out"].begin(pattern);
        try {
          await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.());
          const seen = new Set<string>();
          for (let stop = 0; stop < STOPS; stop++) {
            await page.keyboard.press("Tab");
            const hidden = await page.evaluate(() => {
              const element = document.activeElement as HTMLElement | null;
              if (!element || element === document.body) return null;
              const box = element.getBoundingClientRect();
              if (box.width < 2 || box.height < 2) return null;
              const label = (element.getAttribute("aria-label") || element.textContent || "")
                .trim()
                .replace(/[0-9]+/g, "")
                .replace(/\s+/g, " ")
                .slice(0, 28);
              const points = [
                [box.left + box.width / 2, box.top + box.height / 2],
                [box.left + 2, box.top + 2],
                [box.right - 2, box.top + 2],
                [box.left + 2, box.bottom - 2],
                [box.right - 2, box.bottom - 2]
              ].filter(([x, y]) => x! >= 0 && x! < innerWidth && y! >= 0 && y! < innerHeight);
              if (points.length === 0) return null;
              const covers = points.map(([x, y]) => {
                const top = document.elementFromPoint(x!, y!);
                // A tooltip of the stop before is still fading out when keys come fast; it
                // is transient content (1.4.13), not a bar the page keeps over the focus.
                if (top?.closest("[role=tooltip], .astryx-tooltip")) return null;
                return top && !element.contains(top) && !top.contains(element) ? top : null;
              });
              if (covers.some((top) => top === null)) return null;
              const top = covers[0]!;
              const style = getComputedStyle(
                top.closest("[data-docked-actions], header, nav, aside") ?? top
              );
              return {
                name: `${element.tagName.toLowerCase()}:${label}`,
                by: `${top.tagName.toLowerCase()}${top.className ? "." + String(top.className).split(" ")[0] : ""} (${style.position})`
              };
            });
            if (hidden && !seen.has(hidden.name)) {
              seen.add(hidden.name);
              problems.push(`${pattern}: ${hidden.name} is entirely hidden by ${hidden.by}`);
            }
          }
        } catch (error) {
          throw watch[signedIn ? "in" : "out"].explain(error);
        }
      }
      for (const context of Object.values(contexts)) await context.close();
      expect(problems, problems.join("\n")).toEqual([]);
    }
  );
}
