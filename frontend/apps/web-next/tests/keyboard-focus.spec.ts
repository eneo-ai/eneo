import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";
import { createFixtures, openRoute } from "./responsive-fixtures";
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
 */

const STOPS = 30;
const PAD = 6;
const VIEWPORT = { width: 1280, height: 800 };

test(
  "every screen starts at the skip link and draws its keyboard focus",
  { tag: ["@vite", "@keyboard"] },
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
    const problems: string[] = [];

    for (const [pattern, entry] of Object.entries(ROUTES)) {
      if ("skip" in entry) continue;
      const signedIn = entry.auth !== "out";
      const page = pages[signedIn ? "in" : "out"];
      try {
        await openRoute(page, entry.url(fixtures), signedIn);
      } catch (error) {
        problems.push(`${pattern}: did not open (${String(error).split("\n")[0]})`);
        continue;
      }
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
    }
    for (const context of Object.values(contexts)) await context.close();
    expect(problems, problems.join("\n")).toEqual([]);
  }
);
