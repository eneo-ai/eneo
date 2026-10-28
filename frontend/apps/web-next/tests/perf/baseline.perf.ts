// Framework-neutral performance baseline for web-next (P0-baseline-harness).
// It measures any running build (Next now, the Vite build in phase 6) the same
// way and writes JSON, so the phase 6 gate compares like with like.
//
//   PERF=1 E2E_USER=... E2E_PASSWORD=... bunx playwright test --project=perf
//
// Options: RUNS (default 10; chat warm LCP is bimodal and 5 runs move its median by
// about 25%), PERF_OUT (default test-results/perf-baseline.json),
// PERF_FRAMEWORK (default "next"; the package whose version goes in meta).
import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { devices, expect, test, type Browser, type Page } from "@playwright/test";
import { STORAGE_STATE } from "../../playwright.config";
import { askChatQuestion, chatComposer, conversationLog, MOCK_REPLY, uniqueName } from "../helpers";

const RUNS = Number(process.env.RUNS ?? 10);
const OUT = process.env.PERF_OUT ?? "test-results/perf-baseline.json";
const FRAMEWORK = process.env.PERF_FRAMEWORK ?? "next";
const ROUTES = ["/spaces/personal/chat", "/spaces/list", "/admin/users", "/admin/insights"];
// Wait for rendered page content, not a framework signal (P4 probe: #root for Vite).
const CONTENT = "#main-content > *, #root > *";
const SETTLE_MS = 2_000;

type Samples = Record<string, Record<string, number[]>>;
type Summary = { median: number; p75: number };

function quantile(values: number[], q: number) {
  const sorted = [...values].sort((a, b) => a - b);
  const index = (sorted.length - 1) * q;
  const low = sorted[Math.floor(index)] ?? 0;
  const high = sorted[Math.ceil(index)] ?? 0;
  return low + (high - low) * (index - Math.floor(index));
}

function summarize(samples: Samples) {
  const metrics: Record<string, Record<string, Summary>> = {};
  for (const [route, byMetric] of Object.entries(samples)) {
    metrics[route] = {};
    for (const [metric, values] of Object.entries(byMetric)) {
      metrics[route][metric] = { median: quantile(values, 0.5), p75: quantile(values, 0.75) };
    }
  }
  return metrics;
}

function record(samples: Samples, route: string, metric: string, value: number) {
  samples[route] ??= {};
  (samples[route][metric] ??= []).push(value);
}

/** Starts buffered LCP, CLS and event-timing observers before the page's own scripts run. */
async function observe(page: Page) {
  await page.addInitScript(() => {
    const perf = { lcp: 0, cls: 0, inp: 0 };
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
      for (const entry of list.getEntries()) perf.inp = Math.max(perf.inp, entry.duration);
    }).observe({ type: "event", buffered: true, durationThreshold: 16 } as PerformanceObserverInit);
  });
}

function readPerf(page: Page) {
  return page.evaluate(
    () => (window as unknown as { __perf: { lcp: number; cls: number; inp: number } }).__perf
  );
}

async function load(page: Page, route: string) {
  await page.goto(route);
  await page.locator(CONTENT).first().waitFor();
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
    await expect(nav.locator("#main-content").getByRole("heading", { level: 1 })).toBeVisible();
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

    await chat.evaluate(() => {
      (window as unknown as { __perf: { inp: number } }).__perf.inp = 0;
    });
    await chatComposer(chat).pressSequentially("abcdefghijklmnopqrst");
    for (let toggle = 0; toggle < 2; toggle += 1) {
      await chat
        .getByRole("button", {
          name: /^(fäll (ihop|ut) sidomenyn|(collapse|expand) the side menu)$/i
        })
        .click();
    }
    await chat.waitForTimeout(SETTLE_MS);
    record(samples, "/spaces/personal/chat", "inpMs", (await readPerf(chat)).inp);
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
