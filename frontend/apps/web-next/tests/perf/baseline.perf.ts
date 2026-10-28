// Framework-neutral performance baseline for web-next (P0-baseline-harness).
// It measures any running build (Next now, the Vite build in phase 6) the same
// way and writes JSON, so the phase 6 gate compares like with like.
//
//   PERF=1 E2E_USER=... E2E_PASSWORD=... bunx playwright test --project=perf
//
// Options: RUNS (a positive integer, default 10; chat warm LCP is bimodal and
// 5 runs move its median by about 25%), PERF_OUT (default
// test-results/perf-baseline.json), PERF_FRAMEWORK (default "next"; the package
// whose version goes in meta).
import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { devices, expect, test, type Browser, type Locator, type Page } from "@playwright/test";
import { STORAGE_STATE } from "../../playwright.config";
import { askChatQuestion, chatComposer, conversationLog, MOCK_REPLY, uniqueName } from "../helpers";
import { parseRuns, summarize, worstInteractionMs, type EventEntry, type Samples } from "./metrics";

const RUNS = parseRuns(process.env.RUNS);
const OUT = process.env.PERF_OUT ?? "test-results/perf-baseline.json";
const FRAMEWORK = process.env.PERF_FRAMEWORK ?? "next";
const SETTLE_MS = 2_000;
// A sample counts only once the requested page itself rendered. These markers
// are framework-neutral (the Vite build renders the same features), and none of
// them is part of the error screen.
const PAGE_MARKERS: Record<string, (page: Page) => Locator> = {
  "/spaces/personal/chat": (page) => chatComposer(page),
  "/spaces/list": (page) =>
    page.getByRole("heading", { level: 1, name: /^(alla ytor|ytor|all spaces|spaces)$/i }),
  "/admin/users": (page) => page.getByRole("heading", { level: 1, name: /^(användare|users)$/i }),
  "/admin/insights": (page) => page.getByRole("button", { name: /^(jämför|compare)$/i })
};
const ROUTES = Object.keys(PAGE_MARKERS);
const ERROR_SCREEN = /^(något gick fel|something went wrong)$/i;

function marker(page: Page, route: string) {
  const find = PAGE_MARKERS[route];
  if (!find) throw new Error(`No page marker for ${route}`);
  return find(page);
}

/** Fails unless the route's own content is visible and the error screen is not. */
async function expectRendered(page: Page, route: string) {
  await expect(marker(page, route)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: ERROR_SCREEN })).toHaveCount(0);
}

function record(samples: Samples, route: string, metric: string, value: number) {
  samples[route] ??= {};
  (samples[route][metric] ??= []).push(value);
}

/** Starts buffered LCP, CLS and event-timing observers before the page's own scripts run. */
async function observe(page: Page) {
  await page.addInitScript(() => {
    const perf = { lcp: 0, cls: 0, events: [] as EventEntry[] };
    (window as unknown as { __perf: typeof perf }).__perf = perf;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) perf.lcp = entry.startTime;
    }).observe({ type: "largest-contentful-paint", buffered: true });
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries() as (PerformanceEntry & {
        value: number;
        hadRecentInput: boolean;
      })[]) {
        if (!entry.hadRecentInput) perf.cls += entry.value;
      }
    }).observe({ type: "layout-shift", buffered: true });
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries() as (PerformanceEntry & { interactionId: number })[]) {
        const { interactionId, startTime, duration } = entry;
        perf.events.push({ interactionId, startTime, duration });
      }
    }).observe({ type: "event", buffered: true, durationThreshold: 16 } as PerformanceObserverInit);
  });
}

function readPerf(page: Page) {
  return page.evaluate(
    () =>
      (window as unknown as { __perf: { lcp: number; cls: number; events: EventEntry[] } }).__perf
  );
}

async function load(page: Page, route: string) {
  const response = await page.goto(route);
  expect(response?.ok(), `${route} answered ${response?.status()}`).toBe(true);
  await expectRendered(page, route);
  await page.waitForTimeout(SETTLE_MS);
  const vitals = await readPerf(page);
  const html = await page.evaluate(() => {
    const nav = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming;
    return { encoded: nav.encodedBodySize, decoded: nav.decodedBodySize };
  });
  return { ...vitals, html };
}

async function newPage(browser: Browser) {
  const context = await browser.newContext({
    ...devices["Desktop Chrome"],
    storageState: STORAGE_STATE
  });
  const page = await context.newPage();
  await observe(page);
  return page;
}

function frameworkVersion() {
  try {
    return (
      createRequire(path.join(process.cwd(), "package.json"))(`${FRAMEWORK}/package.json`) as {
        version: string;
      }
    ).version;
  } catch {
    return "unknown";
  }
}

test("performance baseline", async ({ browser }) => {
  test.setTimeout(RUNS * 5 * 60_000);
  const samples: Samples = {};

  for (let run = 0; run < RUNS; run += 1) {
    for (const route of ROUTES) {
      const page = await newPage(browser);
      const cold = await load(page, route);
      record(samples, route, "coldLcpMs", cold.lcp);
      record(samples, route, "coldCls", cold.cls);
      record(samples, route, "htmlEncodedBytes", cold.html.encoded);
      record(samples, route, "htmlDecodedBytes", cold.html.decoded);
      const warm = await load(page, route);
      record(samples, route, "warmLcpMs", warm.lcp);
      record(samples, route, "warmCls", warm.cls);
      await page.context().close();
    }

    // Client navigation: side nav from the chat to the spaces list.
    const nav = await newPage(browser);
    await load(nav, "/spaces/personal/chat");
    const started = Date.now();
    await nav
      .getByRole("navigation", { name: /huvudmeny|main menu/i })
      .getByRole("link", { name: /^(alla ytor|all spaces)$/i })
      .click();
    await nav.waitForURL(/\/spaces\/list$/);
    await expectRendered(nav, "/spaces/list");
    record(samples, "/spaces/personal/chat", "navigationToSpacesListMs", Date.now() - started);
    await nav.context().close();

    // Chat time to first token, then INP over typing and side-nav toggles.
    const chat = await newPage(browser);
    await load(chat, "/spaces/personal/chat");
    const asked = Date.now();
    await askChatQuestion(chat, uniqueName("perf ttft"));
    await expect(conversationLog(chat).getByText(MOCK_REPLY.slice(0, 12))).toBeVisible({
      timeout: 30_000
    });
    record(samples, "/spaces/personal/chat", "chatTtftMs", Date.now() - asked);

    // Only interactions from here on: entries of the question just sent stay out.
    const since = await chat.evaluate(() => performance.now());
    await chatComposer(chat).pressSequentially("abcdefghijklmnopqrst");
    for (let toggle = 0; toggle < 2; toggle += 1) {
      await chat
        .getByRole("button", {
          name: /^(fäll (ihop|ut) sidomenyn|(collapse|expand) the side menu)$/i
        })
        .click();
    }
    await chat.waitForTimeout(SETTLE_MS);
    const { events } = await readPerf(chat);
    record(samples, "/spaces/personal/chat", "inpMs", worstInteractionMs(events, since));
    await chat.context().close();
  }

  const report = {
    meta: {
      commit: execSync("git rev-parse HEAD").toString().trim(),
      framework: FRAMEWORK,
      frameworkVersion: frameworkVersion(),
      node: process.version,
      os: `${os.platform()} ${os.release()}`,
      cpu: os.cpus()[0]?.model ?? "unknown",
      date: new Date().toISOString(),
      runs: RUNS
    },
    metrics: summarize(samples),
    // Raw values, so a gate can judge spread and not only the medians.
    samples
  };
  mkdirSync(path.dirname(OUT), { recursive: true });
  writeFileSync(OUT, `${JSON.stringify(report, null, 2)}\n`);
});

// Negative case: the app's error screen (src/app/(app)/error.tsx) must never pass
// as a rendered page.
test("an error screen is not accepted as a rendered page", async ({ page }) => {
  await page.setContent(
    `<main id="main-content"><div><h1>Något gick fel</h1><p>Ett fel uppstod.</p>` +
      `<button>Försök igen</button></div></main>`
  );
  for (const route of ROUTES) {
    await expect(marker(page, route)).toHaveCount(0);
  }
  await expect(page.getByRole("heading", { name: ERROR_SCREEN })).toHaveCount(1);
});
