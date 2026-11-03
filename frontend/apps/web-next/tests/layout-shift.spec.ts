import type { BrowserContext, CDPSession } from "@playwright/test";
import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";
import { createFixtures, openRoute } from "./responsive-fixtures";
import { ROUTES, type Fixtures } from "./responsive-routes";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

/*
 * Cumulative layout shift (Core Web Vitals; WCAG 3.2.x is about change on request, but a page
 * that moves under a finger or a reading eye is the same fault). Content that arrives late
 * above or beside what is already in view pushes it: a settings card shown before the editor
 * that fills the space over it, a spinner that widens a button, a field that appears once
 * there are enough rows. Each route is opened cold, on a phone profile with the CPU four times
 * slower and a Fast 4G network, so data arrives after the first paint as it does for a person;
 * a fast machine hides what that person sees. 0.1 is "good". Chromium only (CDP throttling).
 * One test per route, so a retry repeats one route. LAYOUT_ROUTES narrows a run to routes
 * matching a regular expression.
 */

const BUDGET = 0.1;
const SETTLE_MS = 3000;
/**
 * route pattern → budget, with the reason. Fix instead of adding to this.
 */
const EXCEPTIONS: Record<string, number> = {};

const PROBE = `
  window.__shifts = { total: 0, entries: [] };
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      if (entry.hadRecentInput) continue;
      window.__shifts.total += entry.value;
      window.__shifts.entries.push({
        value: entry.value,
        nodes: (entry.sources || []).map((s) => s.node ? s.node.nodeName.toLowerCase() + '.' + String(s.node.className).split(' ')[0] : '?').join(' | ')
      });
    }
  }).observe({ type: 'layout-shift', buffered: true });
`;

test.describe(
  "no screen shifts by more than 0.1 while it loads on a slow phone",
  { tag: ["@vite", "@layout-shift"] },
  () => {
    let fixtures: Fixtures;
    test.beforeAll(async ({ browser, baseURL }) => {
      test.setTimeout(60_000);
      fixtures = await createFixtures(browser, baseURL, "Shift");
    });

    for (const [pattern, entry] of Object.entries(ROUTES)) {
      if ("skip" in entry) continue;
      if (process.env.LAYOUT_ROUTES && !new RegExp(process.env.LAYOUT_ROUTES).test(pattern))
        continue;
      test(pattern, async ({ browser, baseURL }) => {
        test.setTimeout(60_000);
        const signedIn = entry.auth !== "out";
        const context: BrowserContext = await browser.newContext({
          baseURL,
          storageState: signedIn ? STORAGE_STATE : { cookies: [], origins: [] },
          viewport: { width: 390, height: 844 },
          deviceScaleFactor: 2,
          hasTouch: true,
          isMobile: true
        });
        try {
          const page = await context.newPage();
          await page.addInitScript(PROBE);
          const cdp: CDPSession = await context.newCDPSession(page);
          await cdp.send("Network.enable");
          await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
          await cdp.send("Network.emulateNetworkConditions", {
            offline: false,
            latency: 150,
            downloadThroughput: (9 * 1024 * 1024) / 8,
            uploadThroughput: (1.5 * 1024 * 1024) / 8
          });
          await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
          await openRoute(page, entry.url(fixtures), signedIn);
          await page.waitForTimeout(SETTLE_MS);
          const shifts = await page.evaluate(
            () =>
              (
                window as unknown as {
                  __shifts: { total: number; entries: { value: number; nodes: string }[] };
                }
              ).__shifts
          );
          const worst = [...shifts.entries].sort((a, b) => b.value - a.value)[0];
          expect(
            shifts.total,
            `shifts ${shifts.total.toFixed(3)} (most: ${worst?.value.toFixed(3)} on ${worst?.nodes})`
          ).toBeLessThanOrEqual(EXCEPTIONS[pattern] ?? BUDGET);
        } finally {
          await context.close();
        }
      });
    }
  }
);
