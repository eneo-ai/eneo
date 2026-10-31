import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";
import { createFixtures, openRoute } from "./responsive-fixtures";
import { measure } from "./responsive-measure";
import { ROUTES } from "./responsive-routes";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

/*
 * Text enlarged to 200% (WCAG 1.4.4; a phone's "larger text", a browser's
 * font size) on a 390 px phone: no screen may scroll sideways as a whole.
 * Every rem grows with the text, buttons and bars included, so a bar that
 * lined up its controls in a row at 100% pushes the page wide at 200%
 * (the phone top bar did, on every screen). A table or a tab strip scrolling
 * inside its own region is fine, and is not measured here. Never baselined.
 */
test(
  "no screen scrolls sideways with the text at 200%",
  { tag: ["@vite", "@text-size"] },
  async ({ browser, baseURL }) => {
    test.setTimeout(15 * 60_000);
    const fixtures = await createFixtures(browser, baseURL, "Text");
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
      // Through the CSSOM: the page's CSP forbids an inline <style>.
      await page.evaluate(() =>
        document.documentElement.style.setProperty("font-size", "200%", "important")
      );
      await page.waitForTimeout(400);
      const { overflowDoc } = await measure(page);
      if (overflowDoc > 0)
        problems.push(`${pattern}: the page scrolls sideways by ${overflowDoc} px`);
    }
    for (const context of Object.values(contexts)) await context.close();
    expect(problems, problems.join("\n")).toEqual([]);
  }
);
