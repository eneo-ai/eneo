// Framework-neutral performance baseline for web-next (P0-baseline-harness).
// It measures any running build (Next now, the Vite build in phase 6) the same
// way and writes JSON, so the phase 6 gate compares like with like.
//
//   PERF=1 E2E_USER=... E2E_PASSWORD=... bunx playwright test --project=perf
//
// Options: RUNS (a positive integer, default 30, the sample count of the
// committed baseline, fixed before measuring), PERF_OUT (default
// test-results/perf-baseline.json), PERF_FRAMEWORK (default "next"; the package
// whose version goes in meta). Two consecutive runs are judged by the stability
// rule in metrics.ts (compareRuns).
//
// The chat page's load metric is chat readiness (coldChatReadyMs,
// warmChatReadyMs): milliseconds from navigation start to the first animation
// frame in which the composer is visible, editable and focusable. Its LCP is
// recorded too, but only for information (compareRuns says why).
import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { expect, test, type Browser, type Locator, type Page } from "@playwright/test";
import {
  askChatQuestion,
  CHAT_COMPOSER_NAME,
  chatComposer,
  CONVERSATION_LOG_NAME,
  conversationLog,
  MOCK_REPLY,
  uniqueName
} from "../helpers";
import {
  CHAT_ROUTE,
  parseRuns,
  summarize,
  worstInteractionMs,
  type EventEntry,
  type Samples
} from "./metrics";

const RUNS = parseRuns(process.env.RUNS);
const OUT = process.env.PERF_OUT ?? "test-results/perf-baseline.json";
const FRAMEWORK = process.env.PERF_FRAMEWORK ?? "next";
const SETTLE_MS = 2_000;
const SPACES_LIST = "/spaces/list";
const SPACES_LIST_HEADING = /^(alla ytor|ytor|all spaces|spaces)$/i;
// The mock answer's first characters, which the chat shows once it streams in.
const ANSWER_START = MOCK_REPLY.slice(0, 12);
// A sample counts only once the requested page itself rendered. These markers
// are framework-neutral (the Vite build renders the same features), and none of
// them is part of the error screen.
const PAGE_MARKERS: Record<string, (page: Page) => Locator> = {
  [CHAT_ROUTE]: (page) => chatComposer(page),
  [SPACES_LIST]: (page) => page.getByRole("heading", { level: 1, name: SPACES_LIST_HEADING }),
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

/**
 * Starts buffered LCP, CLS and event-timing observers before the page's own
 * scripts run, and gives the page its stamps (performance.now() by name):
 * `stampClick` takes one when the next click reaches the window, before any app
 * handler sees it; `stampFrame` takes one in the first animation frame in which
 * a condition holds. A frame, not a DOM mutation, because the browser renders
 * nothing before its render-blocking styles and a style change alone can hide
 * an element; the checks are native DOM, so they read the same in any framework.
 *
 * On the chat route it stamps chat readiness (`chatReady`): the first frame in
 * which the composer is visible, editable and focusable.
 */
async function observe(page: Page) {
  await page.addInitScript(
    ({ chatRoute, composerName }) => {
      const perf: PagePerf = {
        lcp: 0,
        cls: 0,
        events: [],
        stamps: {},
        composer: null,
        stampClick: (stamp) =>
          addEventListener("click", () => (perf.stamps[stamp] = performance.now()), {
            capture: true,
            once: true
          }),
        stampFrame: (stamp, holds) => {
          const frame = () => {
            if (holds()) perf.stamps[stamp] = performance.now();
            else requestAnimationFrame(frame);
          };
          requestAnimationFrame(frame);
        }
      };
      (window as unknown as { __perf: PagePerf }).__perf = perf;
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
        for (const entry of list.getEntries() as (PerformanceEntry & {
          interactionId: number;
        })[]) {
          const { interactionId, startTime, duration } = entry;
          perf.events.push({ interactionId, startTime, duration });
        }
      }).observe({
        type: "event",
        buffered: true,
        durationThreshold: 16
      } as PerformanceObserverInit);

      if (location.pathname !== chatRoute) return;
      const name = new RegExp(...composerName);
      perf.stampFrame("chatReady", () => {
        // The textbox chatComposer() finds; chatReadyMs() checks it is the same element.
        const composer = [
          ...document.querySelectorAll<HTMLElement>('textarea, input, [role="textbox"]')
        ].find((element) => name.test(element.getAttribute("aria-label") ?? ""));
        if (!composer) return false;
        const { width, height } = composer.getBoundingClientRect();
        const ready =
          width > 0 &&
          height > 0 &&
          composer.checkVisibility({ opacityProperty: true, visibilityProperty: true }) &&
          composer.matches(":read-write") &&
          composer.tabIndex >= 0 &&
          !composer.closest("[inert]");
        if (ready) perf.composer = composer;
        return ready;
      });
    },
    // addInitScript passes its argument as JSON, so the pattern travels as source and flags.
    {
      chatRoute: CHAT_ROUTE,
      composerName: [CHAT_COMPOSER_NAME.source, CHAT_COMPOSER_NAME.flags] as [string, string]
    }
  );
}

/** What the init script keeps on `window.__perf`. */
type PagePerf = {
  lcp: number;
  cls: number;
  events: EventEntry[];
  stamps: Record<string, number>;
  /** The element the `chatReady` stamp was taken on. */
  composer: Element | null;
  stampClick: (stamp: string) => void;
  stampFrame: (stamp: string, holds: () => boolean) => void;
};

/** Chat readiness of the loaded page, stamped on the element chatComposer() finds. */
async function chatReadyMs(page: Page) {
  const stamp = await chatComposer(page).evaluate((element) => {
    const { composer, stamps } = (window as unknown as { __perf: PagePerf }).__perf;
    return composer === element ? (stamps.chatReady ?? null) : null;
  });
  if (stamp === null) throw new Error("The readiness probe did not stamp the chat composer");
  return stamp;
}

/** Milliseconds between two of the page's stamps; fails when either was not taken. */
async function stampedMs(page: Page, from: string, to: string) {
  const stamps = await page.evaluate(
    () => (window as unknown as { __perf: PagePerf }).__perf.stamps
  );
  const [start, end] = [stamps[from], stamps[to]];
  if (start === undefined || end === undefined) {
    throw new Error(`The page stamped ${JSON.stringify(stamps)}, not ${from} and ${to}`);
  }
  return end - start;
}

function readPerf(page: Page) {
  return page.evaluate(() => {
    const { lcp, cls, events } = (window as unknown as { __perf: PagePerf }).__perf;
    return { lcp, cls, events };
  });
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

/** A page in a fresh context; the perf project's `use` (playwright.config.ts) sets its options. */
async function newPage(browser: Browser) {
  const page = await (await browser.newContext()).newPage();
  await observe(page);
  return page;
}

/**
 * Side-nav navigation from the chat to the spaces list: from the click to the
 * first animation frame in which the URL is the list's and its heading is
 * visible, both stamped in the page. The Playwright checks only gate that the
 * list rendered.
 */
async function navigationToSpacesListMs(page: Page) {
  await page.evaluate(
    ({ path, heading }) => {
      const perf = (window as unknown as { __perf: PagePerf }).__perf;
      perf.stampClick("navigated");
      perf.stampFrame(
        "listShown",
        () =>
          location.pathname === path &&
          [...document.querySelectorAll("h1")].some(
            (h1) =>
              heading.test((h1.textContent ?? "").trim()) &&
              h1.checkVisibility({ opacityProperty: true, visibilityProperty: true })
          )
      );
    },
    { path: SPACES_LIST, heading: SPACES_LIST_HEADING }
  );
  await page
    .getByRole("navigation", { name: /huvudmeny|main menu/i })
    .getByRole("link", { name: /^(alla ytor|all spaces)$/i })
    .click();
  await page.waitForURL(/\/spaces\/list$/);
  await expectRendered(page, SPACES_LIST);
  return stampedMs(page, "navigated", "listShown");
}

/**
 * Chat time to first token: from the send click to the first animation frame in
 * which the conversation log shows the start of the mock answer, both stamped
 * in the page. The Playwright assertion only gates that the answer rendered.
 */
async function chatTtftMs(page: Page) {
  await page.evaluate(
    ({ answer, logName }) => {
      const perf = (window as unknown as { __perf: PagePerf }).__perf;
      perf.stampClick("asked");
      perf.stampFrame("answered", () =>
        [...document.querySelectorAll('[role="log"]')].some(
          (log) =>
            logName.test(log.getAttribute("aria-label") ?? "") &&
            (log.textContent ?? "").includes(answer)
        )
      );
    },
    { answer: ANSWER_START, logName: CONVERSATION_LOG_NAME }
  );
  await askChatQuestion(page, uniqueName("perf ttft"));
  await expect(conversationLog(page).getByText(ANSWER_START)).toBeVisible({ timeout: 30_000 });
  return stampedMs(page, "asked", "answered");
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
      if (route === CHAT_ROUTE) record(samples, route, "coldChatReadyMs", await chatReadyMs(page));
      const warm = await load(page, route);
      record(samples, route, "warmLcpMs", warm.lcp);
      record(samples, route, "warmCls", warm.cls);
      if (route === CHAT_ROUTE) record(samples, route, "warmChatReadyMs", await chatReadyMs(page));
      await page.context().close();
    }

    // Client navigation: side nav from the chat to the spaces list.
    const nav = await newPage(browser);
    await load(nav, CHAT_ROUTE);
    record(samples, CHAT_ROUTE, "navigationToSpacesListMs", await navigationToSpacesListMs(nav));
    await nav.context().close();

    // Chat time to first token, then INP over typing and side-nav toggles.
    const chat = await newPage(browser);
    await load(chat, CHAT_ROUTE);
    record(samples, CHAT_ROUTE, "chatTtftMs", await chatTtftMs(chat));

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
    record(samples, CHAT_ROUTE, "inpMs", worstInteractionMs(events, since));
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

// The readiness probe stamps the composer only once it is visible, editable and focusable.
test("chat readiness waits for a visible, editable and focusable composer", async ({ page }) => {
  await observe(page);
  await page.route(`**${CHAT_ROUTE}`, (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<main><textarea aria-label="Message to Eneo" hidden></textarea></main>`
    })
  );
  await page.goto(CHAT_ROUTE);
  // The stamp two animation frames later, so a ready composer had a frame to be seen in.
  const stampAfterFrames = () =>
    page.evaluate(
      () =>
        new Promise<number | null>((resolve) =>
          requestAnimationFrame(() =>
            requestAnimationFrame(() =>
              resolve((window as unknown as { __perf: PagePerf }).__perf.stamps.chatReady ?? null)
            )
          )
        )
    );
  // One unmet condition at a time; each step lifts it and sets the next one.
  const steps: [string, (element: HTMLTextAreaElement) => void][] = [
    [
      "hidden",
      (element) => {
        element.hidden = false;
        element.style.opacity = "0";
      }
    ],
    [
      "transparent",
      (element) => {
        element.style.opacity = "";
        element.disabled = true;
      }
    ],
    [
      "disabled",
      (element) => {
        element.disabled = false;
        element.readOnly = true;
      }
    ],
    [
      "read-only",
      (element) => {
        element.readOnly = false;
        element.tabIndex = -1;
      }
    ],
    [
      "unfocusable",
      (element) => {
        element.removeAttribute("tabindex");
        document.body.inert = true;
      }
    ]
  ];
  for (const [state, next] of steps) {
    expect(await stampAfterFrames(), `no stamp while ${state}`).toBeNull();
    await page.locator("textarea").evaluate(next);
  }
  expect(await stampAfterFrames(), "no stamp while inert").toBeNull();
  const readySince = await page.evaluate(() => {
    document.body.inert = false;
    return performance.now();
  });
  const stamp = await stampAfterFrames();
  expect(stamp).toBeGreaterThanOrEqual(readySince);
  // Stamped on the element chatComposer() finds.
  expect(await chatReadyMs(page)).toBe(stamp);
});

// Click-to-render timings come from the page's own stamps: an app that renders
// 300 ms after the click must measure about 300 ms, not the next poll of the
// Playwright assertion that gates the render (770 ms on its retry schedule).
test("click-to-render timings are stamped in the page, not when the assertion passes", async ({
  page
}) => {
  await observe(page);
  await page.route(`**${CHAT_ROUTE}`, (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<main>
        <nav aria-label="Main menu"><a href="/spaces/list">All spaces</a></nav>
        <textarea aria-label="Message to Eneo"></textarea><button>Send message</button>
      </main>
      <script>
        const app = (window.app = {});
        const main = document.querySelector("main");
        const renderLater = (html, path) => {
          app.clickedAt = performance.now();
          setTimeout(() => {
            if (path) history.pushState(null, "", path);
            main.insertAdjacentHTML("beforeend", html);
            app.renderedAt = performance.now();
          }, 300);
        };
        document.querySelector("button").addEventListener("click", () =>
          renderLater('<div role="log" aria-label="Conversation">${MOCK_REPLY}</div>')
        );
        document.querySelector("a").addEventListener("click", (event) => {
          event.preventDefault();
          renderLater("<h1>All spaces</h1>", "/spaces/list");
        });
      </script>`
    })
  );
  await page.goto(CHAT_ROUTE);
  const appDelay = async () => {
    const { clickedAt, renderedAt } = await page.evaluate(
      () => (window as unknown as { app: { clickedAt: number; renderedAt: number } }).app
    );
    return renderedAt - clickedAt;
  };
  for (const measure of [chatTtftMs, navigationToSpacesListMs]) {
    const measured = await measure(page);
    const delay = await appDelay();
    expect(measured, measure.name).toBeGreaterThanOrEqual(delay);
    // Within a frame or two of the render.
    expect(measured, measure.name).toBeLessThan(delay + 50);
  }
});
