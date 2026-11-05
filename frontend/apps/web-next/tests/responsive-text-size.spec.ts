import type { Browser, Page } from "@playwright/test";
import { expect, test } from "./csp";
import { createFixtures, walkRoutes } from "./responsive-fixtures";
import { measure } from "./responsive-measure";

/*
 * What the reader changes about the text, on a 390 px phone, must not cost
 * content. Never baselined: a screen either survives it or does not.
 *
 * - Text at 200% (WCAG 1.4.4; a phone's "larger text", a browser's font size):
 *   no screen may scroll sideways as a whole, and no text may be cut off at the
 *   bottom of its box that was not at 100%. Every rem grows with the text,
 *   buttons and bars included, so a bar that lined up its controls in a row at
 *   100% pushes the page wide at 200% (the phone top bar did, on every
 *   screen). A table or a tab strip scrolling inside its own region is fine.
 * - The text spacing of WCAG 1.4.12 (line height 1.5, paragraph spacing 2,
 *   letter spacing 0.12, word spacing 0.16, all in em): no text may be cut off
 *   that was not cut off without it, and the page must not scroll sideways.
 */

const SPACING = `
  * { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }
  p { margin-block-end: 2em !important; }
`;

/** Opens every screen of the route list on a phone and collects what `check` objects to. */
async function walkScreens(
  browser: Browser,
  baseURL: string | undefined,
  prefix: string,
  check: (page: Page, pattern: string) => Promise<string[]>
) {
  const fixtures = await createFixtures(browser, baseURL, prefix);
  const context = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true };
  return walkRoutes(browser, { baseURL, fixtures, context }, check);
}

test(
  "no screen scrolls sideways with the text at 200%",
  { tag: "@text-size" },
  async ({ browser, baseURL }) => {
    test.setTimeout(15 * 60_000);
    const problems = await walkScreens(browser, baseURL, "Text", async (page, pattern) => {
      // Through the CSSOM: the page's CSP forbids an inline <style>.
      const before = await measure(page, { vertical: true });
      await page.evaluate(() =>
        document.documentElement.style.setProperty("font-size", "200%", "important")
      );
      await page.waitForTimeout(400);
      const after = await measure(page, { vertical: true });
      const was = new Set(before.violations.filter((v) => v.kind === "clippedY").map((v) => v.key));
      const cut = after.violations.filter((v) => v.kind === "clippedY" && !was.has(v.key));
      return [
        ...(after.overflowDoc > 0
          ? [`${pattern}: the page scrolls sideways by ${after.overflowDoc} px`]
          : []),
        ...cut.map((v) => `${pattern}: text cut off at the bottom at 200%: ${v.key}`)
      ];
    });
    expect(problems, problems.join("\n")).toEqual([]);
  }
);

test(
  "no text is cut off, and nothing scrolls sideways, with the text spacing of WCAG 1.4.12",
  { tag: "@text-size" },
  async ({ browser, baseURL }) => {
    test.setTimeout(15 * 60_000);
    const problems = await walkScreens(browser, baseURL, "Spacing", async (page, pattern) => {
      const clipped = (result: Awaited<ReturnType<typeof measure>>) =>
        new Set(
          result.violations
            .filter((v) => v.kind === "clipped" || v.kind === "clippedY")
            .map((v) => v.key)
        );
      const before = await measure(page, { vertical: true });
      // A constructed stylesheet, which the page's CSP allows (an inline <style> it forbids).
      await page.evaluate((css) => {
        const sheet = new CSSStyleSheet();
        sheet.replaceSync(css);
        document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
      }, SPACING);
      await page.waitForTimeout(400);
      const after = await measure(page, { vertical: true });
      const was = clipped(before);
      const cut = [...clipped(after)].filter((key) => !was.has(key));
      return [
        ...(after.overflowDoc > before.overflowDoc
          ? [`${pattern}: the page scrolls sideways by ${after.overflowDoc} px`]
          : []),
        ...cut.map((key) => `${pattern}: text cut off: ${key}`)
      ];
    });
    expect(problems, problems.join("\n")).toEqual([]);
  }
);
