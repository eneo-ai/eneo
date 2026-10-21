import type { CrawlRun } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { readable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { formatDateMedium, formatDateTime } from "$lib/core/formatting/dateTime";
import { crawlRunFailureMessage } from "$lib/features/knowledge/crawlRunState";
import { addressParams, restoreFrameUrl } from "$lib/test/shallowRouting";

const latestRun = vi.hoisted(() => vi.fn());
const listRuns = vi.hoisted(() => vi.fn());
const listBlobs = vi.hoisted(() => vi.fn());
const listFolders = vi.hoisted(() => vi.fn());
const createRun = vi.hoisted(() => vi.fn());
const cancelRun = vi.hoisted(() => vi.fn());
const listFailures = vi.hoisted(() => vi.fn());
const showError = vi.hoisted(() => vi.fn());
vi.mock("$lib/core/errors", async (importOriginal) => ({
  ...(await importOriginal<typeof import("$lib/core/errors")>()),
  toastError: showError
}));
const route = vi.hoisted(() => ({
  url: new URL("http://localhost/?tab=crawls"),
  state: { tab: "crawls" } as { tab?: string }
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    websites: {
      crawlRuns: {
        latest: latestRun,
        listPage: listRuns,
        cancel: cancelRun,
        create: createRun,
        failures: listFailures
      },
      indexedBlobs: { listPage: listBlobs, folders: listFolders }
    }
  })
}));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ state: { currentSpace: readable({ routeId: "space-1" }) } })
}));
vi.mock("$app/state", () => ({ page: route }));
vi.mock("$app/stores", () => ({ page: readable(route) }));
vi.mock("$app/navigation", async () => {
  const { replaceShallowState } = await import("$lib/test/shallowRouting");
  return {
    afterNavigate: vi.fn(),
    beforeNavigate: vi.fn(),
    goto: vi.fn(),
    invalidate: vi.fn(),
    invalidateAll: vi.fn(),
    onNavigate: vi.fn(),
    preloadCode: vi.fn(),
    preloadData: vi.fn(),
    pushState: vi.fn(),
    replaceState: (url: URL | string, state: { tab?: string }) =>
      replaceShallowState(route, url, state)
  };
});

import WebsiteDetailPage from "./+page.svelte";

const running: CrawlRun = {
  id: "run-1",
  created_at: "2026-09-04T07:00:00Z",
  pages_crawled: 2,
  files_downloaded: null,
  pages_failed: null,
  files_failed: null,
  status: "in progress",
  phase: "running",
  outcome: null,
  origin: "scheduled",
  result_location: null,
  finished_at: null,
  failure_code: null,
  failure_detail: null,
  cancel_requested_at: null,
  attempt_count: 1
};
const terminal: CrawlRun = {
  ...running,
  phase: "terminal",
  status: "complete",
  outcome: "succeeded"
};
const emptyPage = {
  items: [],
  count: 0,
  total_count: 0,
  limit: 100,
  next_cursor: null,
  previous_cursor: null
};
const data = {
  website: { id: "website-1", name: "Test website", url: "https://example.test" },
  crawlRuns: [],
  nextCrawlRunCursor: null,
  totalCrawlRunCount: 0,
  infoBlobPage: emptyPage,
  currentSpace: { name: "Test space", personal: false },
  readonly: true,
  environment: {}
};

beforeEach(() => {
  route.url = new URL("http://localhost/?tab=crawls");
  route.state = { tab: "crawls" };
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  latestRun.mockReset().mockResolvedValue(running);
  listRuns.mockReset().mockResolvedValue({ ...emptyPage, items: [running], total_count: 1 });
  listBlobs.mockReset().mockResolvedValue(emptyPage);
  listFolders.mockReset().mockResolvedValue({ items: [], next_cursor: null });
  createRun.mockReset().mockResolvedValue({});
  cancelRun.mockReset().mockResolvedValue({});
  listFailures.mockReset();
  showError.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
  restoreFrameUrl();
});

test("opens Content by default without fetching problem details", async () => {
  route.url = new URL("http://localhost/");
  route.state = {};
  render(WebsiteDetailPage, { data: data as never });
  await expect
    .element(page.getByRole("tab", { name: m.source_tab_content() }))
    .toHaveAttribute("aria-selected", "true");
  expect(listFailures).not.toHaveBeenCalled();
});

test("loads the latest completed crawl's grouped problems only when selected", async () => {
  const completed: CrawlRun = {
    ...terminal,
    id: "completed",
    outcome: "partial",
    pages_failed: 2,
    failure_summary: { http_404: 2 }
  };
  listFailures.mockResolvedValue({
    ...emptyPage,
    run: completed,
    details_available: true,
    items: [
      { id: "failure-one", url: "https://example.test/missing", kind: "page", reason: "http_404" }
    ],
    total_count: 2,
    next_cursor: "failure-one"
  });
  render(WebsiteDetailPage, { data: { ...data, crawlRuns: [running, completed] } as never });
  expect(listFailures).not.toHaveBeenCalled();
  await page.getByRole("tab", { name: m.source_tab_problems() }).click();
  await expect
    .element(page.getByRole("link", { name: "https://example.test/missing" }))
    .toBeVisible();
  await expect
    .element(page.getByText(m.website_source_problem_count({ shown: 1, total: 2 })))
    .toBeVisible();
  expect(listFailures).toHaveBeenCalledExactlyOnceWith({
    id: "completed",
    limit: 100,
    cursor: null
  });
  await page.getByRole("tab", { name: m.source_tab_activity() }).click();
  await expect
    .element(page.getByRole("tab", { name: m.source_tab_activity() }))
    .toHaveAttribute("aria-selected", "true");
});

test("opens a crawl's failed addresses and retries the next page without losing results", async () => {
  const run = {
    ...terminal,
    outcome: "partial",
    pages_failed: 2,
    failure_code: "remote_unreachable"
  };
  const first = {
    id: "failure-1",
    url: "https://example.test/guide.pdf",
    reason: "http_404",
    kind: "file"
  };
  listFailures.mockResolvedValueOnce({
    ...emptyPage,
    run,
    details_available: true,
    items: [first],
    total_count: 2,
    next_cursor: "failure-1"
  });
  render(WebsiteDetailPage, { data: { ...data, crawlRuns: [run] } as never });
  await page.getByRole("tab", { name: m.source_tab_problems() }).click();
  const panel = page.getByRole("tabpanel", { name: m.source_tab_problems() });
  await expect.element(panel.getByRole("link", { name: first.url })).toBeVisible();
  expect(listFailures).toHaveBeenCalledWith({ id: run.id, limit: 100, cursor: null });
  listFailures.mockRejectedValueOnce(new Error("Temporary failure"));
  await panel.getByRole("button", { name: /1.*2/ }).click();
  await expect.element(panel.getByRole("button", { name: m.retry(), exact: true })).toBeVisible();
  await expect.element(panel.getByRole("link", { name: first.url })).toBeVisible();
  listFailures.mockResolvedValueOnce({
    ...emptyPage,
    run,
    details_available: true,
    items: [{ ...first, id: "failure-2", url: "https://example.test/missing", kind: "page" }],
    total_count: 2
  });
  await panel.getByRole("button", { name: m.retry(), exact: true }).click();
  await expect
    .element(panel.getByRole("link", { name: "https://example.test/missing" }))
    .toBeVisible();
  expect(listFailures).toHaveBeenLastCalledWith({ id: run.id, limit: 100, cursor: "failure-1" });
});

test.each([false, true])(
  "failure details distinguish unavailable history from no failures (%s)",
  async (available) => {
    listFailures.mockRejectedValueOnce(new Error("Temporary failure"));
    render(WebsiteDetailPage, { data: { ...data, crawlRuns: [terminal] } as never });
    await page.getByRole("tab", { name: m.source_tab_problems() }).click();
    const panel = page.getByRole("tabpanel", { name: m.source_tab_problems() });
    await expect.element(panel.getByRole("alert")).toBeVisible();
    listFailures.mockResolvedValueOnce({
      ...emptyPage,
      run: terminal,
      details_available: available
    });
    await panel.getByRole("button", { name: m.retry(), exact: true }).click();
    await expect
      .element(
        panel.getByText(available ? m.crawl_failures_empty() : m.crawl_failures_unavailable())
      )
      .toBeVisible();
  }
);

test("older history has a loading state and retries without losing the current run", async () => {
  let rejectPage: (error: Error) => void = () => {};
  listRuns.mockImplementationOnce(
    () =>
      new Promise((_resolve, reject) => {
        rejectPage = reject;
      })
  );
  render(WebsiteDetailPage, {
    data: {
      ...data,
      crawlRuns: [running],
      nextCrawlRunCursor: "older-page",
      totalCrawlRunCount: 2
    } as never
  });
  const label = m.website_crawl_history_load_more({ current: 1, total: 2 });
  await page.getByRole("button", { name: label }).click();
  expect(listRuns).toHaveBeenCalledWith({ id: "website-1", limit: 100, cursor: "older-page" });
  await expect.element(page.getByRole("button", { name: m.loading_more() })).toBeDisabled();
  rejectPage(new Error("History unavailable"));
  await expect.element(page.getByRole("button", { name: label })).toBeEnabled();
  expect(showError).toHaveBeenCalledOnce();
  await expect.element(page.getByText(m.in_progress(), { exact: true }).first()).toBeVisible();

  listRuns.mockResolvedValue({
    ...emptyPage,
    total_count: 2,
    items: [{ ...terminal, id: "older", outcome: "empty" }]
  });
  await page.getByRole("button", { name: label }).click();
  await expect
    .element(page.getByText(m.crawl_status_empty(), { exact: true }).first())
    .toBeVisible();
  await expect.element(page.getByText(m.in_progress(), { exact: true }).first()).toBeVisible();
  await expect.element(page.getByRole("button", { name: label })).not.toBeInTheDocument();
});

test.each([terminal, null])(
  "a pending poll preserves the last older history page (%#)",
  async (latest) => {
    let resolveLatest: (run: CrawlRun | null) => void = () => {};
    latestRun.mockImplementationOnce(
      () =>
        new Promise<CrawlRun | null>((resolve) => {
          resolveLatest = resolve;
        })
    );
    listRuns.mockResolvedValue({
      ...emptyPage,
      total_count: 2,
      items: [{ ...terminal, id: "older", outcome: "empty" }]
    });
    render(WebsiteDetailPage, {
      data: {
        ...data,
        crawlRuns: [running],
        nextCrawlRunCursor: "older-page",
        totalCrawlRunCount: 2
      } as never
    });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(latestRun).toHaveBeenCalledOnce();

    const label = m.website_crawl_history_load_more({ current: 1, total: 2 });
    await page.getByRole("button", { name: label }).click();
    await expect
      .element(page.getByText(m.crawl_status_empty(), { exact: true }).first())
      .toBeVisible();
    await expect.element(page.getByRole("button", { name: label })).not.toBeInTheDocument();

    resolveLatest(latest);
    await vi.advanceTimersByTimeAsync(0);
    if (latest) {
      await expect
        .element(page.getByText(m.crawl_status_succeeded(), { exact: true }).first())
        .toBeVisible();
    }
    await expect
      .element(page.getByText(m.crawl_status_empty(), { exact: true }).first())
      .toBeVisible();
    expect(listRuns).toHaveBeenCalledOnce();
  }
);

test("an idle mounted page discovers and displays a scheduled crawl, then refreshes its results", async () => {
  render(WebsiteDetailPage, { data: data as never });
  await vi.advanceTimersByTimeAsync(10_000);
  expect(latestRun).toHaveBeenCalledOnce();
  await expect.element(page.getByText(m.in_progress(), { exact: true }).first()).toBeVisible();

  latestRun.mockResolvedValue(terminal);
  listBlobs.mockResolvedValue({
    ...emptyPage,
    count: 1,
    total_count: 1,
    items: [{ id: "blob-1", metadata: { title: "Indexed report", size: 100 }, text: "Content" }]
  });
  await vi.advanceTimersByTimeAsync(10_000);
  await expect
    .element(page.getByText(m.crawl_status_succeeded(), { exact: true }).first())
    .toBeVisible();
  expect(listBlobs).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(10_000);
  expect(listRuns).toHaveBeenCalledOnce();
  expect(listBlobs).toHaveBeenCalledOnce();
  await page.getByRole("tab", { name: m.source_tab_content(), exact: true }).click();
  await expect.element(page.getByText("Indexed report", { exact: true })).toBeVisible();
});

test("polls never overlap, recover after a network error, and stop on unmount", async () => {
  let rejectRequest: (reason: Error) => void = () => {};
  latestRun.mockImplementationOnce(
    () =>
      new Promise((_resolve, reject) => {
        rejectRequest = reject;
      })
  );
  const view = render(WebsiteDetailPage, { data: data as never });
  await vi.advanceTimersByTimeAsync(30_000);
  expect(latestRun).toHaveBeenCalledOnce();
  rejectRequest(new Error("Network unavailable"));
  await vi.advanceTimersByTimeAsync(10_000);
  expect(latestRun).toHaveBeenCalledTimes(2);
  await expect.element(page.getByText(m.in_progress(), { exact: true }).first()).toBeVisible();
  await view.unmount();
  await vi.advanceTimersByTimeAsync(30_000);
  expect(latestRun).toHaveBeenCalledTimes(2);
});

test("a content refresh failure keeps the terminal status and retries without clearing old content", async () => {
  const oldPage = {
    ...emptyPage,
    count: 1,
    total_count: 1,
    items: [{ id: "old-blob", metadata: { title: "Previous report", size: 100 } }]
  };
  latestRun.mockResolvedValue(terminal);
  listBlobs.mockRejectedValueOnce(new Error("Content service unavailable"));
  render(WebsiteDetailPage, {
    data: { ...data, crawlRuns: [running], infoBlobPage: oldPage } as never
  });
  await vi.advanceTimersByTimeAsync(10_000);
  await expect
    .element(page.getByText(m.crawl_status_succeeded(), { exact: true }).first())
    .toBeVisible();
  await page.getByRole("tab", { name: m.source_tab_content(), exact: true }).click();
  await expect.element(page.getByText("Previous report", { exact: true })).toBeVisible();
  listBlobs.mockResolvedValue({
    ...oldPage,
    items: [{ id: "new-blob", metadata: { title: "Updated report", size: 100 } }]
  });
  await vi.advanceTimersByTimeAsync(10_000);
  expect(listBlobs).toHaveBeenCalledTimes(2);
  await expect.element(page.getByText("Updated report", { exact: true })).toBeVisible();
  await expect.element(page.getByText("Previous report", { exact: true })).not.toBeInTheDocument();
});

test("history failures do not hide the latest status or block content, and history recovers", async () => {
  latestRun.mockResolvedValue(terminal);
  listRuns.mockRejectedValue(new Error("History temporarily unavailable"));
  render(WebsiteDetailPage, { data: data as never });

  await vi.advanceTimersByTimeAsync(10_000);
  await expect
    .element(page.getByText(m.crawl_status_succeeded(), { exact: true }).first())
    .toBeVisible();
  expect(listBlobs).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(10_000);
  expect(listRuns).toHaveBeenCalledTimes(2);

  // A stale history response must not overwrite the confirmed terminal state.
  const older = { ...terminal, id: "older-run", pages_crawled: 1 };
  listRuns.mockResolvedValue({ ...emptyPage, items: [running, older], total_count: 2 });
  await vi.advanceTimersByTimeAsync(10_000);
  expect(listRuns).toHaveBeenCalledTimes(3);
  await expect
    .element(page.getByText(m.in_progress(), { exact: true }).first())
    .not.toBeInTheDocument();
  await expect
    .poll(
      () =>
        page
          .getByRole("tabpanel", { name: m.source_tab_activity() })
          .getByText(m.crawl_status_succeeded(), { exact: true })
          .all().length
    )
    .toBe(2);
  await vi.advanceTimersByTimeAsync(10_000);
  expect(listRuns).toHaveBeenCalledTimes(3);
  expect(listBlobs).toHaveBeenCalledOnce();
});

test("a terminal refresh discards an older load-more response even if the cursor is reused", async () => {
  const oldFirstPage = {
    ...emptyPage,
    count: 1,
    total_count: 2,
    next_cursor: "page-2",
    items: [{ id: "old-first", metadata: { title: "Old first page", size: 100 } }]
  };
  const oldSecondPage = {
    ...emptyPage,
    count: 1,
    total_count: 2,
    items: [{ id: "old-second", metadata: { title: "Old second page", size: 100 } }]
  };
  let resolveOldPage: (value: typeof oldSecondPage) => void = () => {};
  listBlobs.mockImplementationOnce(
    () => new Promise<typeof oldSecondPage>((resolve) => (resolveOldPage = resolve))
  );
  render(WebsiteDetailPage, {
    data: { ...data, crawlRuns: [running], infoBlobPage: oldFirstPage } as never
  });
  await page.getByRole("tab", { name: m.source_tab_content(), exact: true }).click();
  await page
    .getByRole("button", { name: m.website_indexed_content_load_more({ current: 1, total: 2 }) })
    .click();
  expect(listBlobs).toHaveBeenCalledWith({ id: "website-1", limit: 100, cursor: "page-2" });

  latestRun.mockResolvedValue(terminal);
  listBlobs.mockResolvedValue({
    ...oldFirstPage,
    items: [{ id: "new-first", metadata: { title: "New first page", size: 100 } }]
  });
  await vi.advanceTimersByTimeAsync(10_000);
  await expect.element(page.getByText("New first page", { exact: true })).toBeVisible();

  await expect
    .element(
      page.getByRole("button", {
        name: m.website_indexed_content_load_more({ current: 1, total: 2 })
      })
    )
    .toBeEnabled();
  let resolveNewPage: (value: typeof oldSecondPage) => void = () => {};
  listBlobs.mockImplementationOnce(
    () => new Promise<typeof oldSecondPage>((resolve) => (resolveNewPage = resolve))
  );
  await page
    .getByRole("button", { name: m.website_indexed_content_load_more({ current: 1, total: 2 }) })
    .click();
  resolveOldPage(oldSecondPage);
  await expect.element(page.getByRole("button", { name: m.loading_more() })).toBeDisabled();
  await expect.element(page.getByText("Old second page", { exact: true })).not.toBeInTheDocument();
  resolveNewPage({
    ...oldSecondPage,
    items: [{ id: "new-second", metadata: { title: "New second page", size: 100 } }]
  });
  await expect.element(page.getByText("New second page", { exact: true })).toBeVisible();
  await expect.element(page.getByText("New first page", { exact: true })).toBeVisible();
});

test.each([running, terminal])(
  "crawl controls use the latest run while history is unavailable (phase: $phase)",
  async (latest) => {
    latestRun.mockResolvedValue(latest);
    listRuns.mockRejectedValue(new Error("History temporarily unavailable"));
    render(WebsiteDetailPage, {
      data: { ...data, readonly: false, crawlRuns: [{ ...running, id: "older-run" }] } as never
    });
    await vi.advanceTimersByTimeAsync(10_000);

    if (latest.phase === "terminal") {
      await expect.element(page.getByRole("button", { name: m.run_crawl_again() })).toBeVisible();
      await expect
        .element(page.getByRole("button", { name: m.stop_crawl(), exact: true }))
        .not.toBeInTheDocument();
    } else {
      await page.getByRole("button", { name: m.stop_crawl(), exact: true }).click();
      await page
        .getByRole("alertdialog")
        .getByRole("button", { name: m.stop_crawl(), exact: true })
        .click();
      expect(cancelRun).toHaveBeenCalledWith(latest);
    }
  }
);

test.each([false, true])(
  "refreshes a run completed entirely between polls (existing history: %s)",
  async (hasHistory) => {
    const previous = { ...terminal, id: "previous-run" };
    latestRun.mockResolvedValue(terminal);
    listRuns.mockResolvedValue({
      ...emptyPage,
      items: [terminal, ...(hasHistory ? [previous] : [])],
      total_count: hasHistory ? 2 : 1
    });
    render(WebsiteDetailPage, {
      data: { ...data, crawlRuns: hasHistory ? [previous] : [] } as never
    });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(listBlobs).toHaveBeenCalledWith({ id: "website-1", limit: 100 });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(listBlobs).toHaveBeenCalledOnce();
    expect(listRuns).toHaveBeenCalledOnce();
  }
);

test("the Problems file filter selects files and ignores an old response after switching", async () => {
  const run: CrawlRun = {
    ...terminal,
    outcome: "partial",
    pages_failed: 104,
    files_failed: 2,
    failure_summary: { http_404: 2, _RedirectRejected: 104 }
  };
  const file = {
    id: "file-1",
    url: "https://example.test/missing.pdf",
    kind: "file",
    reason: "http_404"
  };
  let resolveFilePage: (value: unknown) => void = () => {};
  listFailures.mockResolvedValue({
    ...emptyPage,
    run,
    details_available: true,
    items: [file],
    total_count: 2,
    next_cursor: file.id
  });
  render(WebsiteDetailPage, { data: { ...data, crawlRuns: [run] } as never });
  await page.getByRole("button", { name: m.website_source_see_problems() }).click();
  await page.getByRole("button", { name: m.crawl_counts_files(), exact: true }).click();
  const panel = page.getByRole("tabpanel", { name: m.source_tab_problems() });
  await expect.element(panel.getByRole("link", { name: file.url })).toBeVisible();
  expect(listFailures).toHaveBeenLastCalledWith({
    id: run.id,
    limit: 100,
    cursor: null,
    kind: "file"
  });
  await expect
    .element(panel.getByRole("button", { name: m.crawl_counts_files(), exact: true }))
    .toHaveAttribute("aria-pressed", "true");
  listFailures.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveFilePage = resolve;
      })
  );
  await panel
    .getByRole("button", { name: m.crawl_failures_load_more({ current: 1, total: 2 }) })
    .click();
  expect(listFailures).toHaveBeenLastCalledWith({
    id: run.id,
    limit: 100,
    cursor: file.id,
    kind: "file"
  });
  const address = "https://example.test/moved";
  listFailures.mockResolvedValueOnce({
    ...emptyPage,
    run,
    details_available: true,
    items: [{ id: "page-1", url: address, kind: "page", reason: "_RedirectRejected" }],
    total_count: 104
  });
  await panel.getByRole("button", { name: m.crawl_counts_pages(), exact: true }).click();
  await expect.element(panel.getByRole("link", { name: address })).toBeVisible();
  expect(listFailures).toHaveBeenLastCalledWith({
    id: run.id,
    limit: 100,
    cursor: null,
    kind: "page"
  });
  resolveFilePage({
    ...emptyPage,
    run,
    details_available: true,
    items: [{ ...file, id: "file-2" }],
    total_count: 2
  });
  await expect.element(panel.getByRole("link", { name: file.url })).not.toBeInTheDocument();
  await panel.getByRole("button", { name: m.crawl_failures_filter_all(), exact: true }).click();
  await expect.element(panel.getByText(m.crawl_failure_help_scope())).toBeVisible();
  await expect.element(panel.getByText(m.crawl_failure_help_not_found())).toBeVisible();
  await expect
    .element(panel.getByText("_RedirectRejected", { exact: false }))
    .not.toBeInTheDocument();
  await expect
    .element(panel.getByRole("button", { name: m.crawl_retry_whole_website() }))
    .not.toBeInTheDocument();
});

test.each(["processing_failed", "resources_missing"] as const)(
  "indexed content retains %s details until a clean crawl replaces them",
  async (failure_code) => {
    route.url = new URL("http://localhost/?tab=blobs");
    route.state = { tab: "blobs" };
    const run: CrawlRun = {
      ...terminal,
      id: "completed-run",
      outcome: "partial",
      pages_failed: 6,
      files_failed: 2,
      failure_code
    };
    const notice =
      failure_code === "resources_missing"
        ? m.crawl_content_has_missing()
        : m.crawl_content_has_failures();
    listFailures.mockResolvedValue({ ...emptyPage, run, details_available: true });
    const rendered = render(WebsiteDetailPage, {
      data: { ...data, crawlRuns: [running, run] } as never
    });
    await expect.element(page.getByRole("heading", { name: notice })).toBeVisible();
    await page.getByRole("button", { name: m.website_source_see_problems() }).click();
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
    await expect
      .element(page.getByRole("tab", { name: m.source_tab_problems() }))
      .toHaveAttribute("aria-selected", "true");
    expect(addressParams().get("tab")).toBe("problems");
    if (failure_code === "resources_missing") {
      await expect
        .element(
          page
            .getByRole("tabpanel", { name: m.source_tab_problems() })
            .getByText(m.crawl_status_succeeded(), { exact: true })
        )
        .toBeVisible();
    }
    expect(listFailures).toHaveBeenCalledWith({
      id: run.id,
      limit: 100,
      cursor: null
    });
    await page.getByRole("tab", { name: m.source_tab_content() }).click();
    await rendered.rerender({
      data: {
        ...data,
        infoBlobPage: { ...emptyPage, items: [] },
        crawlRuns: [{ ...terminal, id: "clean-run" }, { ...run }]
      } as never
    });
    await expect.element(page.getByRole("heading", { name: notice })).not.toBeInTheDocument();
  }
);

test("retrying from failure details uses the existing whole-website confirmation", async () => {
  const run: CrawlRun = { ...terminal, outcome: "partial", pages_failed: 1 };
  listFailures.mockResolvedValue({ ...emptyPage, run, details_available: true });
  render(WebsiteDetailPage, { data: { ...data, readonly: false, crawlRuns: [run] } as never });
  await page.getByRole("button", { name: m.website_source_see_problems() }).click();
  await page.getByRole("button", { name: m.crawl_retry_whole_website() }).click();
  const confirmation = page.getByRole("alertdialog");
  await expect.element(confirmation).toBeVisible();
  expect(createRun).not.toHaveBeenCalled();
  await confirmation.getByRole("button", { name: m.start_crawl(), exact: true }).click();
  expect(createRun).toHaveBeenCalledExactlyOnceWith(data.website);
});

test("activity groups crawls by date and opens an older run in Problems without a dialog", async () => {
  const latest: CrawlRun = { ...terminal, id: "newest", outcome: "partial", pages_failed: 1 };
  const sameDay: CrawlRun = { ...terminal, id: "same-day", created_at: "2026-09-04T06:00:00Z" };
  const older: CrawlRun = { ...latest, id: "older", created_at: "2026-09-03T07:00:00Z" };
  listFailures.mockImplementation(async ({ id }: { id: string }) => ({
    ...emptyPage,
    run: id === older.id ? older : latest,
    details_available: true
  }));
  render(WebsiteDetailPage, { data: { ...data, crawlRuns: [latest, sameDay, older] } as never });
  const activity = page.getByRole("tabpanel", { name: m.source_tab_activity() });
  await expect
    .element(
      activity.getByRole("heading", { name: formatDateMedium(latest.created_at), exact: true })
    )
    .toBeVisible();
  expect(activity.getByRole("heading").all().length).toBe(2);
  await expect.element(activity.getByRole("table")).not.toBeInTheDocument();
  await activity.getByRole("button", { name: m.website_source_see_problems() }).last().click();
  await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
  const problems = page.getByRole("tabpanel", { name: m.source_tab_problems() });
  await expect
    .element(problems.getByRole("heading", { name: m.website_source_previous_crawl() }))
    .toBeVisible();
  await expect
    .element(
      problems.getByText(
        m.website_source_problems_description({ date: formatDateTime(older.created_at) })
      )
    )
    .toBeVisible();
  expect(listFailures).toHaveBeenLastCalledWith({ id: older.id, limit: 100, cursor: null });
  await problems.getByLabelText(m.website_source_choose_crawl()).selectOptions(latest.id);
  await expect
    .element(problems.getByRole("heading", { name: m.website_source_latest_completed() }))
    .toBeVisible();
  expect(listFailures).toHaveBeenLastCalledWith({ id: latest.id, limit: 100, cursor: null });
});

test("activity retains a legacy crawl whose start date is unknown", async () => {
  render(WebsiteDetailPage, {
    data: { ...data, crawlRuns: [{ ...terminal, created_at: null }] } as never
  });
  const activity = page.getByRole("tabpanel", { name: m.source_tab_activity() });
  await expect.element(activity.getByRole("heading", { name: m.not_available() })).toBeVisible();
  await expect
    .element(activity.getByText(m.crawl_status_succeeded(), { exact: true }))
    .toBeVisible();
});

test("a poll with a fresh copy of the same finished crawl does not reload its problems", async () => {
  const completed: CrawlRun = {
    ...terminal,
    id: "completed",
    outcome: "partial",
    pages_failed: 1,
    failure_summary: { http_404: 1 }
  };
  listFailures.mockResolvedValue({
    ...emptyPage,
    run: completed,
    details_available: true,
    items: [
      { id: "failure-one", url: "https://example.test/missing", kind: "page", reason: "http_404" }
    ],
    total_count: 1
  });
  latestRun.mockImplementation(async () => ({ ...completed }));
  render(WebsiteDetailPage, { data: { ...data, crawlRuns: [completed] } as never });
  await page.getByRole("tab", { name: m.source_tab_problems() }).click();
  const panel = page.getByRole("tabpanel", { name: m.source_tab_problems() });
  await expect
    .element(panel.getByRole("link", { name: "https://example.test/missing" }))
    .toBeVisible();
  await vi.advanceTimersByTimeAsync(10_000);
  await vi.advanceTimersByTimeAsync(10_000);
  expect(latestRun).toHaveBeenCalledTimes(2);
  expect(listFailures).toHaveBeenCalledOnce();
  await expect.element(panel.getByRole("status")).not.toBeInTheDocument();
  await expect
    .element(panel.getByRole("link", { name: "https://example.test/missing" }))
    .toBeVisible();
});

const siteOrigin = "https://example.test/";
const indexed = (title: string) => ({
  id: title,
  metadata: {
    title,
    url: `${siteOrigin}docs/${title}`,
    size: 10,
    embedding_model_id: "model"
  },
  original_available: false,
  created_at: "2026-10-19T09:00:00Z"
});

test("a selected directory survives a tab switch, on the page and in the address", async () => {
  route.url = new URL("http://localhost/");
  route.state = {};
  listFolders.mockImplementation(async ({ prefix }: { prefix: string }) => ({
    items: prefix
      ? [{ path: `${siteOrigin}docs/`, count: 2, has_children: false }]
      : [{ path: siteOrigin, count: 3, has_children: true }],
    next_cursor: null
  }));
  listBlobs.mockResolvedValue({
    ...emptyPage,
    items: [indexed("Guide")],
    count: 1,
    total_count: 1
  });
  listFailures.mockResolvedValue({ ...emptyPage, run: terminal, details_available: true });
  render(WebsiteDetailPage, {
    data: {
      ...data,
      crawlRuns: [terminal],
      infoBlobPage: { ...emptyPage, total_count: 3 }
    } as never
  });
  await page.getByRole("link", { name: /^docs/ }).click();
  await expect.element(page.getByRole("button", { name: "Guide" })).toBeVisible();
  expect(addressParams().get("prefix")).toBe(`${siteOrigin}docs/`);

  await page.getByRole("tab", { name: m.source_tab_problems() }).click();
  await expect
    .element(page.getByRole("tab", { name: m.source_tab_problems() }))
    .toHaveAttribute("aria-selected", "true");
  expect(addressParams().get("tab")).toBe("problems");
  expect(addressParams().get("prefix")).toBe(`${siteOrigin}docs/`);

  await page.getByRole("tab", { name: m.source_tab_content() }).click();
  await expect
    .element(page.getByRole("link", { name: /^docs/ }))
    .toHaveAttribute("aria-current", "page");
  await expect.element(page.getByRole("button", { name: "Guide" })).toBeVisible();
  expect(listBlobs).toHaveBeenLastCalledWith({
    id: data.website.id,
    limit: 100,
    cursor: null,
    prefix: `${siteOrigin}docs/`
  });
});

test("a deep-linked selection is shown from the server once, then fetched afresh", async () => {
  route.url = new URL(
    `http://localhost/?tab=blobs&prefix=${encodeURIComponent(siteOrigin + "docs/")}`
  );
  route.state = {};
  listBlobs.mockResolvedValue({
    ...emptyPage,
    items: [indexed("Fresh guide")],
    count: 1,
    total_count: 1
  });
  listFailures.mockResolvedValue({ ...emptyPage, run: terminal, details_available: true });
  render(WebsiteDetailPage, {
    data: {
      ...data,
      crawlRuns: [terminal],
      initialContent: {
        prefix: `${siteOrigin}docs/`,
        q: "",
        page: { ...emptyPage, items: [indexed("Server guide")], count: 1, total_count: 1 }
      }
    } as never
  });
  await expect.element(page.getByRole("button", { name: "Server guide" })).toBeVisible();
  expect(listBlobs).not.toHaveBeenCalled();

  await page.getByRole("tab", { name: m.source_tab_problems() }).click();
  await page.getByRole("tab", { name: m.source_tab_content() }).click();
  await expect.element(page.getByRole("button", { name: "Fresh guide" })).toBeVisible();
  expect(listBlobs).toHaveBeenCalledExactlyOnceWith({
    id: data.website.id,
    limit: 100,
    cursor: null,
    prefix: `${siteOrigin}docs/`
  });
});

test("an older crawl chosen in Problems stays selected when the history is replaced", async () => {
  const latest: CrawlRun = { ...terminal, id: "newest", outcome: "partial", pages_failed: 1 };
  const older: CrawlRun = { ...latest, id: "older", created_at: "2026-09-03T07:00:00Z" };
  listFailures.mockImplementation(async ({ id }: { id: string }) => ({
    ...emptyPage,
    run: id === older.id ? older : latest,
    details_available: true
  }));
  const rendered = render(WebsiteDetailPage, {
    data: { ...data, crawlRuns: [latest, older] } as never
  });
  await page.getByRole("tab", { name: m.source_tab_problems() }).click();
  const problems = page.getByRole("tabpanel", { name: m.source_tab_problems() });
  await problems.getByLabelText(m.website_source_choose_crawl()).selectOptions(older.id);
  await expect
    .element(problems.getByRole("heading", { name: m.website_source_previous_crawl() }))
    .toBeVisible();

  const newer: CrawlRun = { ...terminal, id: "newer", created_at: "2026-09-05T07:00:00Z" };
  await rendered.rerender({ data: { ...data, crawlRuns: [newer, latest] } as never });
  await expect
    .element(problems.getByRole("heading", { name: m.website_source_previous_crawl() }))
    .toBeVisible();
  await expect
    .element(problems.getByLabelText(m.website_source_choose_crawl()))
    .toHaveValue(older.id);
  expect(listFailures).toHaveBeenLastCalledWith({ id: older.id, limit: 100, cursor: null });
});

test("activity states why a crawl failed", async () => {
  const failed: CrawlRun = {
    ...terminal,
    id: "failed",
    outcome: "failed",
    failure_code: "worker_interrupted"
  };
  render(WebsiteDetailPage, { data: { ...data, crawlRuns: [failed] } as never });
  const activity = page.getByRole("tabpanel", { name: m.source_tab_activity() });
  await expect.element(activity.getByText(crawlRunFailureMessage(failed))).toBeVisible();
});
