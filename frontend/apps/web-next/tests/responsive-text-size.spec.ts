import type { Browser, Page } from "@playwright/test";
import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";
import { createFixtures, openRoute } from "./responsive-fixtures";
import { measure } from "./responsive-measure";
import { ROUTES } from "./responsive-routes";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

/*
 * What the reader changes about the text, on a 390 px phone, must not cost
 * content. Never baselined: a screen either survives it or does not.
 *
 * - Text at 200% (WCAG 1.4.4; a phone's "larger text", a browser's font size):
 *   no screen may scroll sideways as a whole. Every rem grows with the text,
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
  const viewport = { width: 390, height: 844 };
  const contexts = {
    in: await browser.newContext({
      baseURL,
      storageState: STORAGE_STATE,
      viewport,
      hasTouch: true,
      isMobile: true
    }),
    out: await browser.newContext({
      baseURL,
      storageState: { cookies: [], origins: [] },
      viewport,
      hasTouch: true,
      isMobile: true
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
    problems.push(...(await check(page, pattern)));
  }
  for (const context of Object.values(contexts)) await context.close();
  return problems;
}

test(
  "no screen scrolls sideways with the text at 200%",
  { tag: ["@vite", "@text-size"] },
  async ({ browser, baseURL }) => {
    test.setTimeout(15 * 60_000);
    const problems = await walkScreens(browser, baseURL, "Text", async (page, pattern) => {
      // Through the CSSOM: the page's CSP forbids an inline <style>.
      await page.evaluate(() =>
        document.documentElement.style.setProperty("font-size", "200%", "important")
      );
      await page.waitForTimeout(400);
      const { overflowDoc } = await measure(page);
      return overflowDoc > 0 ? [`${pattern}: the page scrolls sideways by ${overflowDoc} px`] : [];
    });
    expect(problems, problems.join("\n")).toEqual([]);
  }
);

test(
  "no text is cut off, and nothing scrolls sideways, with the text spacing of WCAG 1.4.12",
  { tag: ["@vite", "@text-size"] },
  async ({ browser, baseURL }) => {
    test.setTimeout(15 * 60_000);
    const problems = await walkScreens(browser, baseURL, "Spacing", async (page, pattern) => {
      const clipped = (result: Awaited<ReturnType<typeof measure>>) =>
        new Set(result.violations.filter((v) => v.kind === "clipped").map((v) => v.key));
      const before = await measure(page);
      // A constructed stylesheet, which the page's CSP allows (an inline <style> it forbids).
      await page.evaluate((css) => {
        const sheet = new CSSStyleSheet();
        sheet.replaceSync(css);
        document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
      }, SPACING);
      await page.waitForTimeout(400);
      const after = await measure(page);
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
