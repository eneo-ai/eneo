import { expect, test } from "./csp";
import { createFixtures, walkRoutes } from "./responsive-fixtures";
import type { Fixtures } from "./responsive-routes";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

/*
 * Windows high contrast (WCAG 1.4.11, 1.4.1, 4.1.2). In forced colours the browser
 * swaps every author colour for the system palette: a background that is not a system
 * colour becomes Canvas, the page's own colour, and shadows and tints vanish. A
 * control drawn only as a fill, with no border or outline, is then plain text; a
 * switch whose track and thumb are both Canvas shows no state.
 *
 * The browser's computed styles show it: a control whose forced background is the
 * page's colour and whose border and outline are 0 has no boundary left. A switch
 * is judged by track and thumb: they must not both be the page's colour.
 * Run on the routes the responsive contract walks, on a phone and an iPad.
 * FORCED_ROUTES narrows a run to routes matching a regular expression.
 */

const CONTROLS =
  "button, [role=button], [role=switch], a[href], input:not([type=hidden], [type=checkbox], [type=radio]), select, textarea, summary";
const VARIANTS = [
  { name: "phone", width: 390, height: 844 },
  { name: "ipad", width: 820, height: 1180 }
] as const;

let fixtures: Fixtures;

test.beforeAll(async ({ browser, baseURL }) => {
  fixtures = await createFixtures(browser, baseURL, "Forced");
});

for (const variant of VARIANTS) {
  test(
    `every control keeps a boundary in forced colours on a ${variant.name}`,
    { tag: ["@vite", "@forced-colors"] },
    async ({ browser, baseURL }) => {
      test.setTimeout(15 * 60_000);
      const walk = {
        baseURL,
        fixtures,
        context: {
          viewport: { width: variant.width, height: variant.height },
          forcedColors: "active",
          reducedMotion: "reduce",
          hasTouch: true,
          isMobile: true
        },
        only: process.env.FORCED_ROUTES
      } as const;
      const problems = await walkRoutes(browser, walk, async (page, pattern) => {
        const found = await page.evaluate((selector) => {
          const canvas = getComputedStyle(document.body).backgroundColor;
          const filled = (color: string) => color !== "rgba(0, 0, 0, 0)" && !color.endsWith(", 0)");
          const shown = (element: Element) =>
            element.getClientRects().length > 0 &&
            getComputedStyle(element).visibility !== "hidden" &&
            !element.closest("[inert], [aria-hidden=true]");
          const label = (element: Element) =>
            (element.getAttribute("aria-label") ?? element.textContent ?? "")
              .replace(/[0-9]+/g, "")
              .replace(/\s+/g, " ")
              .trim()
              .toLowerCase()
              .slice(0, 24);
          const out = new Set<string>();
          for (const element of document.querySelectorAll(selector)) {
            if (!shown(element)) continue;
            const style = getComputedStyle(element);
            const box = element.getBoundingClientRect();
            if (box.width <= 1 || box.height <= 1) continue;
            if (element.getAttribute("role") === "switch") {
              // Astryx's switch has its own forced-colours styles; the legacy one is ours.
              if (!element.matches("[data-slot=switch]")) continue;
              const thumb = element.querySelector("[data-slot=switch-thumb], span");
              const track = style.backgroundColor;
              const knob = thumb ? getComputedStyle(thumb).backgroundColor : canvas;
              const border = parseFloat(style.borderTopWidth) > 0;
              if (!border || (track === canvas && knob === canvas))
                out.add(`switch without state: ${label(element)}`);
              continue;
            }
            if (style.backgroundColor !== canvas || !filled(style.backgroundColor)) continue;
            const edge = ["Top", "Right", "Bottom", "Left"].some(
              (side) =>
                parseFloat(style[`border${side}Width` as "borderTopWidth"]) > 0 &&
                style[`border${side}Style` as "borderTopStyle"] !== "none"
            );
            const ring = style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0;
            if (!edge && !ring)
              out.add(`${element.tagName.toLowerCase()} fill without boundary: ${label(element)}`);
          }
          return [...out];
        }, CONTROLS);
        return found.map((item) => `${pattern}: ${item}`);
      });
      expect(problems, problems.join("\n")).toEqual([]);
    }
  );
}
