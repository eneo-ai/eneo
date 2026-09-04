import type { CrawlRun } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { readable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const latestRun = vi.hoisted(() => vi.fn());
const listRuns = vi.hoisted(() => vi.fn());
const listBlobs = vi.hoisted(() => vi.fn());
const cancelRun = vi.hoisted(() => vi.fn());
const route = vi.hoisted(() => ({
  url: new URL("http://localhost/?tab=crawls"),
  state: { tab: "crawls" }
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    websites: {
      crawlRuns: { latest: latestRun, list: listRuns, cancel: cancelRun },
      indexedBlobs: { listPage: listBlobs }
    }
  })
}));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ state: { currentSpace: readable({ routeId: "space-1" }) } })
}));
vi.mock("$app/state", () => ({ page: route }));
vi.mock("$app/stores", () => ({ page: readable(route) }));
vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadCode: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: (url: URL, state: { tab: string }) => {
    route.url = url;
    route.state = state;
  }
}));

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
  listRuns.mockReset().mockResolvedValue([running]);
  listBlobs.mockReset().mockResolvedValue(emptyPage);
  cancelRun.mockReset().mockResolvedValue({});
});
afterEach(() => vi.useRealTimers());

test("an idle mounted page discovers and displays a scheduled crawl, then refreshes its results", async () => {
  render(WebsiteDetailPage, { data: data as never });
  await vi.advanceTimersByTimeAsync(10_000);
  expect(latestRun).toHaveBeenCalledOnce();
  await expect.element(page.getByText(m.in_progress(), { exact: true })).toBeVisible();

  latestRun.mockResolvedValue(terminal);
  listBlobs.mockResolvedValue({
    ...emptyPage,
    count: 1,
    total_count: 1,
    items: [{ id: "blob-1", metadata: { title: "Indexed report", size: 100 }, text: "Content" }]
  });
  await vi.advanceTimersByTimeAsync(10_000);
  await expect.element(page.getByText(m.crawl_status_succeeded(), { exact: true })).toBeVisible();
  expect(listBlobs).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(10_000);
  expect(listRuns).toHaveBeenCalledOnce();
  expect(listBlobs).toHaveBeenCalledOnce();
  await page.getByRole("tab", { name: m.indexed_content(), exact: true }).click();
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
  await expect.element(page.getByText(m.in_progress(), { exact: true })).toBeVisible();
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
  await expect.element(page.getByText(m.crawl_status_succeeded(), { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: m.indexed_content(), exact: true }).click();
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
  await expect.element(page.getByText(m.crawl_status_succeeded(), { exact: true })).toBeVisible();
  expect(listBlobs).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(10_000);
  expect(listRuns).toHaveBeenCalledTimes(2);

  // A stale history response must not overwrite the confirmed terminal state.
  const older = { ...terminal, id: "older-run", pages_crawled: 1 };
  listRuns.mockResolvedValue([running, older]);
  await vi.advanceTimersByTimeAsync(10_000);
  expect(listRuns).toHaveBeenCalledTimes(3);
  await expect.element(page.getByText(m.in_progress(), { exact: true })).not.toBeInTheDocument();
  await expect
    .poll(() => page.getByText(m.crawl_status_succeeded(), { exact: true }).all().length)
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
  await page.getByRole("tab", { name: m.indexed_content(), exact: true }).click();
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
    listRuns.mockResolvedValue([terminal, ...(hasHistory ? [previous] : [])]);
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
