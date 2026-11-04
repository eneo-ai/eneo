import { expect, test } from "./csp";
import { createFixtures, walkRoutes, walkTags } from "./responsive-fixtures";

/*
 * Keyboard on every screen of tests/responsive-routes.ts, on a laptop-sized
 * window: the first Tab lands on the skip link of a signed-in screen (2.4.1),
 * and each of the next 30 stops draws something (2.4.7): a stop whose
 * surroundings look the same focused and blurred has no visible focus. It does
 * not judge how visible, only that it is there; axe cannot see this, since a
 * ring that is styled away is valid CSS. A field is judged by its frame (the
 * ring is on that, not on the <input>), a list row's link by its row.
 *
 * Phones and iPads have their keyboard check on the contract's walk
 * (tests/hidden-focus-probe.ts), which opens the same screens at the same sizes.
 */

const STOPS = 30;
const PAD = 6;
const VIEWPORT = { width: 1280, height: 800 };

test(
  "every screen starts at the skip link and draws its keyboard focus",
  { tag: walkTags("@keyboard", "desktop") },
  async ({ browser, baseURL }) => {
    test.setTimeout(15 * 60_000);
    const fixtures = await createFixtures(browser, baseURL, "Focus");
    const walk = { baseURL, fixtures, context: { viewport: VIEWPORT } };
    const problems = await walkRoutes(browser, walk, async (page, pattern, signedIn) => {
      const found: string[] = [];
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
          found.push(`${pattern}: the first Tab stop is ${focused.name}, not the skip link`);
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
          found.push(`${pattern}: no visible focus on ${focused.name}`);
        // Back where the keyboard was, so the next Tab continues from it.
        await page.keyboard.press("Shift+Tab");
        await page.keyboard.press("Tab");
      }
      return found;
    });
    expect(problems, problems.join("\n")).toEqual([]);
  }
);
