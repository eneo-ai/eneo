import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { AdminCrawlerDetails, AdminCrawlerOverview, CrawlRun } from "@eneo/eneo-js";
import "../../../../app.css";
import { m } from "$lib/paraglide/messages";
import dayjs from "dayjs";
import { crawlRunStateLabel } from "$lib/features/knowledge/crawlRunState";

const api = vi.hoisted(() => ({
  adminCrawler: {
    overview: vi.fn(),
    failures: vi.fn(),
    details: vi.fn(),
    history: vi.fn(),
    matches: vi.fn(),
    start: vi.fn(),
    cancel: vi.fn()
  },
  websites: { crawlRuns: { failures: vi.fn() } }
}));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => api }));
vi.mock("$app/state", () => ({
  page: { url: new URL("http://localhost/admin/crawler"), state: {} }
}));
vi.mock("$app/navigation", () => ({
  replaceState: vi.fn(),
  goto: vi.fn(),
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  onNavigate: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  preloadData: vi.fn(),
  preloadCode: vi.fn(),
  disableScrollHandling: vi.fn()
}));
import CrawlerPage from "./+page.svelte";

const overview: AdminCrawlerOverview = {
  as_of: "2026-09-09T12:00:00Z",
  summary: { ongoing: 1, queued: 0, issues: 2 },
  calendar: {
    time_zone: "Europe/Stockholm",
    today: { date: "2026-09-09", completed: 124, partial: 3, failed: 2, cancelled: 1 },
    yesterday: { date: "2026-09-08", completed: 256, partial: 4, failed: 1, cancelled: 0 }
  },
  next_cursor: null,
  items: [
    {
      website_id: "website-1",
      website_name: "Municipal website",
      website_url: "https://example.test",
      space_name: "Communications",
      started_at: "2026-09-09T11:58:00Z",
      last_indexed_at: null,
      run: {
        id: "run-1",
        created_at: "2026-09-09T11:57:00Z",
        updated_at: "2026-09-09T11:58:00Z",
        phase: "running",
        outcome: null,
        origin: "manual",
        status: "in progress",
        pages_crawled: null,
        pages_failed: null,
        files_downloaded: null,
        files_failed: null,
        result_location: null,
        finished_at: null,
        failure_code: null,
        failure_detail: null,
        cancel_requested_at: null,
        attempt_count: 1
      }
    }
  ]
};

const details: AdminCrawlerDetails = {
  ...overview.items[0],
  space_id: "space-1",
  owner: { id: "owner-1", username: "Alex Sourceowner", email: "alex@example.test" },
  initiated_by: { id: "operator-1", username: "Sam Operator", email: "sam@example.test" },
  indexed_size: 2097152,
  stored_resources: 41,
  update_interval: "daily",
  next_retry_at: null,
  consecutive_failures: 0,
  active_run: overview.items[0].run,
  latest_run: overview.items[0].run
};

beforeEach(async () => {
  document.documentElement.dataset.theme = "light";
  await page.viewport(1180, 900);
  vi.clearAllMocks();
  api.adminCrawler.overview.mockResolvedValue(structuredClone(overview));
  api.adminCrawler.details.mockResolvedValue(structuredClone(details));
  api.adminCrawler.failures.mockResolvedValue({
    run: overview.items[0].run,
    items: [],
    total_count: 0,
    next_cursor: null,
    details_available: true
  });
  api.adminCrawler.history.mockResolvedValue({
    items: [overview.items[0].run],
    total_count: 1,
    next_cursor: null
  });
  api.adminCrawler.matches.mockResolvedValue({ items: [], next_cursor: null });
});

afterEach(() => vi.restoreAllMocks());

function show() {
  const result = render(CrawlerPage);
  result.container.style.cssText =
    "position: relative; z-index: 10; display: flex; height: 100dvh; width: 100%;";
  return result;
}

function failurePage(run: CrawlRun) {
  return { run, items: [], total_count: 0, next_cursor: null, details_available: true };
}

async function openDetails() {
  await page.getByRole("button", { name: "Municipal website", exact: true }).click();
  await expect
    .element(page.getByRole("tab", { name: m.admin_crawler_source(), exact: true }))
    .toBeVisible();
  return page.getByRole("dialog");
}

it("shows failed and unknown resource counts in history without an unusable pager", async () => {
  const previous: CrawlRun = {
    ...details.run,
    phase: "terminal",
    outcome: "partial",
    status: "complete",
    pages_crawled: 12,
    pages_failed: 3,
    files_downloaded: 0,
    files_failed: null
  };
  api.adminCrawler.details.mockResolvedValue({
    ...details,
    run: previous,
    active_run: null,
    latest_run: previous
  });
  api.adminCrawler.failures.mockResolvedValue(failurePage(previous));
  api.adminCrawler.history.mockResolvedValue({
    items: [previous],
    total_count: 1,
    next_cursor: null
  });
  show();
  const dialog = await openDetails();
  await dialog.getByRole("tab", { name: m.history(), exact: true }).click();
  const counts = dialog.getByRole("table", { name: m.crawl_counts_caption(), exact: true });
  await expect
    .element(counts.getByRole("row", { name: `${m.crawl_counts_pages()} 12 3`, exact: true }))
    .toBeVisible();
  await expect
    .element(
      counts.getByRole("row", {
        name: `${m.crawl_counts_files()} 0 ${m.crawl_counts_unknown()}`,
        exact: true
      })
    )
    .toBeVisible();
  await expect
    .element(dialog.getByRole("button", { name: m.admin_crawler_next() }))
    .not.toBeInTheDocument();
  await expect
    .element(dialog.getByRole("button", { name: m.admin_crawler_previous() }))
    .not.toBeInTheDocument();
});

it("separates the selected crawl from current source data and keeps action context across tabs", async () => {
  show();
  await page.getByRole("button", { name: "Municipal website", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect
    .element(dialog.getByRole("tab", { name: m.details(), exact: true }))
    .toHaveAttribute("aria-selected", "true");
  await expect.element(dialog.getByText("Alex Sourceowner", { exact: true })).not.toBeVisible();
  await expect.element(dialog.getByRole("table", { name: m.crawl_counts_caption() })).toBeVisible();
  await dialog.getByRole("tab", { name: m.admin_crawler_source(), exact: true }).click();
  await expect.element(dialog.getByText("Alex Sourceowner", { exact: true })).toBeVisible();
  await expect.element(dialog.getByText("2.0 MB", { exact: true })).toBeVisible();
  await expect.element(dialog.getByText(m.admin_crawler_source_description())).toBeVisible();
  expect(api.adminCrawler.details).toHaveBeenCalledTimes(1);
  await dialog.getByRole("tab", { name: m.history(), exact: true }).click();
  await expect
    .element(
      dialog.getByText(
        m.admin_crawler_selected_run({
          date: dayjs(details.run.created_at).format("YYYY-MM-DD HH:mm")
        }),
        { exact: true }
      )
    )
    .toBeVisible();
  await expect
    .element(dialog.getByRole("button", { name: m.stop_crawl(), exact: true }))
    .toBeVisible();
});

it("updates the available action when failure details contain a newer terminal run", async () => {
  const finished: CrawlRun = {
    ...details.run,
    phase: "terminal",
    outcome: "succeeded",
    status: "complete",
    finished_at: "2026-09-09T12:00:00Z",
    pages_crawled: 12,
    pages_failed: 0,
    files_downloaded: 0,
    files_failed: 0
  };
  api.adminCrawler.failures.mockResolvedValue(failurePage(finished));
  show();
  const dialog = await openDetails();
  await expect
    .element(dialog.getByRole("button", { name: m.run_crawl_again(), exact: true }))
    .toBeVisible();
  await expect
    .element(dialog.getByRole("button", { name: m.stop_crawl(), exact: true }))
    .not.toBeInTheDocument();
  expect(api.adminCrawler.failures).toHaveBeenCalledTimes(1);
  expect(api.adminCrawler.details).toHaveBeenCalledTimes(1);
});

it("keeps failed addresses visible during a details refresh and recovers from a failed replacement", async () => {
  const original = {
    id: "failure-1",
    kind: "page",
    reason: "http_404",
    url: "https://example.test/missing"
  };
  api.adminCrawler.failures.mockResolvedValueOnce({
    ...failurePage(details.run),
    items: [original],
    total_count: 1
  });
  show();
  const dialog = await openDetails();
  await expect.element(dialog.getByRole("link", { name: original.url, exact: true })).toBeVisible();
  let fail: (error: Error) => void = () => {};
  api.adminCrawler.failures.mockReturnValueOnce(
    new Promise((_resolve, reject) => {
      fail = reject;
    })
  );
  await dialog.getByRole("button", { name: m.refresh(), exact: true }).click();
  await expect.poll(() => api.adminCrawler.failures.mock.calls.length).toBe(2);
  await expect.element(dialog.getByRole("link", { name: original.url, exact: true })).toBeVisible();
  await expect
    .element(dialog.getByRole("button", { name: m.refresh(), exact: true }))
    .toBeDisabled();
  fail(new Error("Unavailable"));
  await expect.element(dialog.getByRole("alert")).toHaveTextContent(m.crawl_failures_load_failed());
  await expect.element(dialog.getByRole("link", { name: original.url, exact: true })).toBeVisible();
  const replacement = { ...original, id: "failure-2", url: "https://example.test/revised" };
  api.adminCrawler.failures.mockResolvedValueOnce({
    ...failurePage(details.run),
    items: [replacement],
    total_count: 1
  });
  await dialog.getByRole("button", { name: m.retry(), exact: true }).click();
  await expect
    .element(dialog.getByRole("link", { name: replacement.url, exact: true }))
    .toBeVisible();
  await expect
    .element(dialog.getByRole("link", { name: original.url, exact: true }))
    .not.toBeInTheDocument();
  expect(api.adminCrawler.failures).toHaveBeenLastCalledWith({
    id: "run-1",
    limit: 100,
    cursor: null
  });
});

it("keeps cancellation from history retryable and returns to the updated details", async () => {
  const stopping: CrawlRun = {
    ...details.run,
    phase: "stopping",
    cancel_requested_at: "2026-09-09T12:01:00Z"
  };
  api.adminCrawler.cancel
    .mockRejectedValueOnce(new Error("Connection lost"))
    .mockResolvedValueOnce(stopping);
  show();
  const dialog = await openDetails();
  api.adminCrawler.history.mockResolvedValue({
    items: [details.run],
    next_cursor: null,
    total_count: 1
  });
  await dialog.getByRole("tab", { name: m.history(), exact: true }).click();
  await expect.poll(() => api.adminCrawler.history.mock.calls.length).toBe(1);
  await dialog.getByRole("button", { name: m.stop_crawl(), exact: true }).click();
  const confirmation = page.getByRole("alertdialog");
  await confirmation.getByRole("button", { name: m.stop_crawl(), exact: true }).click();
  await expect
    .element(confirmation.getByRole("alert"))
    .toHaveTextContent(m.admin_crawler_action_error());
  await expect
    .element(confirmation.getByRole("button", { name: m.stop_crawl(), exact: true }))
    .toBeEnabled();
  api.adminCrawler.details.mockResolvedValue({
    ...details,
    run: stopping,
    active_run: stopping,
    latest_run: stopping
  });
  api.adminCrawler.failures.mockResolvedValue(failurePage(stopping));
  await confirmation.getByRole("button", { name: m.stop_crawl(), exact: true }).click();
  await expect
    .element(dialog.getByRole("button", { name: m.stopping_crawl(), exact: true }))
    .toBeDisabled();
  expect(api.adminCrawler.cancel).toHaveBeenCalledTimes(2);
  expect(api.adminCrawler.cancel).toHaveBeenLastCalledWith({ id: "run-1" });
  await expect.element(confirmation).not.toBeInTheDocument();
  await expect
    .element(dialog.getByRole("tab", { name: m.details(), exact: true }))
    .toHaveAttribute("aria-selected", "true");
  await expect.element(dialog.getByRole("table", { name: m.crawl_counts_caption() })).toBeVisible();
});

it.each(["failed", "succeeded"] as const)(
  "confirms a full rerun after %s and selects the returned run",
  async (outcome) => {
    const previous: CrawlRun = {
      ...details.run,
      phase: "terminal",
      outcome,
      status: outcome === "failed" ? "failed" : "complete",
      finished_at: "2026-09-09T12:00:00Z"
    };
    const next: CrawlRun = {
      ...details.run,
      id: "run-2",
      phase: "queued",
      status: "queued",
      created_at: "2026-09-09T12:02:00Z"
    };
    api.adminCrawler.details.mockImplementation(async ({ id }: { id: string }) => ({
      ...details,
      run: id === "run-2" ? next : previous,
      active_run: id === "run-2" ? next : null,
      latest_run: id === "run-2" ? next : previous
    }));
    api.adminCrawler.failures.mockImplementation(async ({ id }: { id: string }) =>
      failurePage(id === "run-2" ? next : previous)
    );
    let finish: (run: CrawlRun) => void = () => {};
    api.adminCrawler.start.mockReturnValueOnce(
      new Promise<CrawlRun>((resolve) => {
        finish = resolve;
      })
    );
    show();
    const dialog = await openDetails();
    const label = outcome === "failed" ? m.admin_crawler_retry_crawl() : m.run_crawl_again();
    await dialog.getByRole("button", { name: label, exact: true }).click();
    const confirmation = page.getByRole("alertdialog");
    await expect
      .element(confirmation)
      .toHaveTextContent(m.admin_crawler_rerun_description({ websiteName: "Municipal website" }));
    await confirmation.getByRole("button", { name: label, exact: true }).click();
    await expect
      .element(confirmation.getByRole("button", { name: m.starting(), exact: true }))
      .toBeDisabled();
    expect(api.adminCrawler.start).toHaveBeenCalledExactlyOnceWith({ id: "website-1" });
    finish(next);
    await expect.poll(() => api.adminCrawler.details.mock.lastCall).toEqual([{ id: "run-2" }]);
    await expect
      .element(dialog.getByRole("button", { name: m.stop_crawl(), exact: true }))
      .toBeVisible();
    await expect.poll(() => api.adminCrawler.overview.mock.calls.length).toBe(2);
  }
);

it("loads history on demand, retries its page, and opens the selected older run", async () => {
  const old: CrawlRun = {
    ...details.run,
    id: "old-run",
    created_at: "2026-09-08T12:00:00Z",
    phase: "terminal",
    outcome: "failed",
    status: "failed"
  };
  api.adminCrawler.history
    .mockRejectedValueOnce(new Error("Unavailable"))
    .mockResolvedValueOnce({ items: [details.run], next_cursor: "history-next", total_count: 2 })
    .mockResolvedValueOnce({ items: [old], next_cursor: null, total_count: 2 });
  const intervals = vi.spyOn(globalThis, "setInterval");
  show();
  const dialog = await openDetails();
  expect(api.adminCrawler.history).not.toHaveBeenCalled();
  expect(api.adminCrawler.matches).not.toHaveBeenCalled();
  const poll = intervals.mock.calls.find(([, delay]) => delay === 10_000)?.[0];
  if (typeof poll !== "function") throw new Error("Missing overview polling");
  poll();
  await expect.poll(() => api.adminCrawler.overview.mock.calls.length).toBe(2);
  expect(api.adminCrawler.details).toHaveBeenCalledTimes(1);
  await dialog.getByRole("tab", { name: m.history(), exact: true }).click();
  await expect
    .element(dialog.getByRole("alert"))
    .toHaveTextContent(m.admin_crawler_history_error());
  await dialog.getByRole("button", { name: m.retry(), exact: true }).click();
  await dialog.getByRole("button", { name: m.admin_crawler_next(), exact: true }).click();
  expect(api.adminCrawler.history).toHaveBeenLastCalledWith({
    id: "website-1",
    limit: 10,
    cursor: "history-next"
  });
  api.adminCrawler.history.mockResolvedValueOnce({
    items: [old],
    next_cursor: null,
    total_count: 2
  });
  await dialog
    .getByRole("button", { name: m.admin_crawler_refresh_history(), exact: true })
    .click();
  expect(api.adminCrawler.history).toHaveBeenLastCalledWith({
    id: "website-1",
    limit: 10,
    cursor: "history-next"
  });
  expect(api.adminCrawler.details).toHaveBeenCalledTimes(1);
  api.adminCrawler.details.mockResolvedValue({ ...details, run: old, active_run: details.run });
  api.adminCrawler.failures.mockResolvedValue(failurePage(old));
  await dialog.getByRole("button", { name: /2026-09-08/ }).click();
  await expect
    .element(dialog.getByRole("button", { name: m.admin_crawler_view_active() }))
    .toBeVisible();
  expect(api.adminCrawler.details).toHaveBeenLastCalledWith({ id: "old-run" });
  await expect
    .element(dialog.getByRole("button", { name: m.admin_crawler_retry_crawl() }))
    .not.toBeInTheDocument();
});

it("shows same-address sources on demand and follows their run without fetching content", async () => {
  const related = {
    ...details,
    website_id: "related-website",
    website_name: "Related source",
    space_name: "Research",
    run: { ...details.run, id: "related-run" }
  };
  api.adminCrawler.matches.mockRejectedValueOnce(new Error("Unavailable")).mockResolvedValueOnce({
    items: [
      {
        website_id: related.website_id,
        website_name: related.website_name,
        website_url: related.website_url,
        space_name: related.space_name,
        indexed_size: 1024,
        last_indexed_at: null,
        latest_run_id: related.run.id
      }
    ],
    next_cursor: null
  });
  show();
  const dialog = await openDetails();
  await dialog.getByRole("tab", { name: m.admin_crawler_same_address() }).click();
  await expect
    .element(dialog.getByRole("alert"))
    .toHaveTextContent(m.admin_crawler_matches_error());
  await dialog.getByRole("button", { name: m.retry(), exact: true }).click();
  await expect.element(dialog.getByText("Research", { exact: true })).toBeVisible();
  api.adminCrawler.details.mockResolvedValue(related);
  api.adminCrawler.failures.mockResolvedValue(failurePage(related.run));
  await dialog.getByRole("button", { name: "Related source", exact: true }).click();
  await expect
    .element(dialog.getByRole("heading", { name: "Related source", exact: true }))
    .toBeVisible();
  expect(api.adminCrawler.details).toHaveBeenCalledTimes(2);
  expect(api.adminCrawler.details).toHaveBeenLastCalledWith({ id: "related-run" });
  expect(api.websites.crawlRuns.failures).not.toHaveBeenCalled();
});

it("ignores an old details response after closing and reopening another crawl", async () => {
  let finish: (value: AdminCrawlerDetails) => void = () => {};
  api.adminCrawler.details.mockReturnValueOnce(
    new Promise<AdminCrawlerDetails>((resolve) => {
      finish = resolve;
    })
  );
  const next = {
    ...details,
    website_id: "website-2",
    website_name: "Second source",
    owner: { ...details.owner, username: "New owner" },
    run: { ...details.run, id: "run-2" }
  };
  api.adminCrawler.overview.mockResolvedValue({
    ...overview,
    items: [...overview.items, { ...next }]
  });
  show();
  await page.getByRole("button", { name: "Municipal website", exact: true }).click();
  await expect.poll(() => api.adminCrawler.details.mock.calls.length).toBe(1);
  await userEvent.keyboard("{Escape}");
  api.adminCrawler.details.mockResolvedValue(next);
  api.adminCrawler.failures.mockResolvedValue(failurePage(next.run));
  await page.getByRole("button", { name: "Second source", exact: true }).click();
  await page.getByRole("tab", { name: m.admin_crawler_source(), exact: true }).click();
  await expect.element(page.getByText("New owner", { exact: true })).toBeVisible();
  finish(details);
  await expect.element(page.getByText("Alex Sourceowner", { exact: true })).not.toBeInTheDocument();
  await expect.element(page.getByText("New owner", { exact: true })).toBeVisible();
});

it.each(["Municipal website", null])(
  "shows tenant metadata and opens admin failures with website name %s",
  async (websiteName) => {
    const sample = structuredClone(overview);
    sample.items[0].website_name = websiteName;
    api.adminCrawler.overview.mockResolvedValue(sample);
    api.adminCrawler.details.mockResolvedValue({ ...details, website_name: websiteName });
    const label = websiteName ?? sample.items[0].website_url;
    api.adminCrawler.failures.mockResolvedValue({
      run: overview.items[0].run,
      items: [],
      total_count: 0,
      next_cursor: null,
      details_available: true
    });
    show();
    await expect.element(page.getByRole("button", { name: label, exact: true })).toBeVisible();
    await expect.element(page.getByText("Communications", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: label, exact: true }).click();
    await expect.element(page.getByText("Sam Operator", { exact: false })).toBeVisible();
    await page.getByRole("tab", { name: m.admin_crawler_source(), exact: true }).click();
    await expect.element(page.getByText("Alex Sourceowner", { exact: true })).toBeVisible();
    await expect.element(page.getByText("2.0 MB", { exact: true })).toBeVisible();
    await expect.poll(() => api.adminCrawler.failures.mock.calls.length).toBe(1);
    expect(api.websites.crawlRuns.failures).not.toHaveBeenCalled();
    await userEvent.keyboard("{Escape}");
    await expect.element(page.getByRole("button", { name: label, exact: true })).toHaveFocus();
  }
);

it("keeps rows and filters when a refresh fails, then retries the same query", async () => {
  const intervals = vi.spyOn(globalThis, "setInterval");
  show();
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .toBeVisible();
  await page.getByRole("textbox", { name: m.admin_crawler_search() }).fill("Municipal");
  await page.getByRole("button", { name: m.search(), exact: true }).click();
  await page.getByRole("button", { name: m.status() }).click();
  await page.getByRole("option", { name: m.in_progress(), exact: true }).click();
  await expect.element(page.getByRole("button", { name: m.refresh(), exact: true })).toBeEnabled();
  const poll = intervals.mock.calls.find(([, delay]) => delay === 10_000)?.[0];
  if (typeof poll !== "function") throw new Error("Missing crawler polling callback");
  api.adminCrawler.overview.mockRejectedValueOnce(new Error("Network unavailable"));
  poll();
  await expect.element(page.getByRole("alert")).toHaveTextContent(m.admin_crawler_refresh_error());
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .toBeVisible();
  await expect
    .element(page.getByRole("textbox", { name: m.admin_crawler_search() }))
    .toHaveValue("Municipal");
  await expect
    .element(page.getByRole("button", { name: m.status() }))
    .toHaveTextContent(m.in_progress());
  const updated = structuredClone(overview);
  updated.items[0].run.pages_crawled = 8;
  let finish: (value: AdminCrawlerOverview) => void = () => {};
  api.adminCrawler.overview.mockReturnValueOnce(
    new Promise<AdminCrawlerOverview>((resolve) => {
      finish = resolve;
    })
  );
  const retryButton = page.getByRole("button", { name: m.retry(), exact: true });
  await retryButton.click();
  await expect.element(retryButton).toBeDisabled();
  await expect.element(retryButton).toHaveAttribute("aria-busy", "true");
  await expect.element(page.getByRole("alert")).toHaveTextContent(m.admin_crawler_refresh_error());
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .toBeVisible();
  finish(updated);
  await expect
    .element(
      page.getByRole("row", {
        name: `${m.crawl_counts_pages()} 8 ${m.crawl_counts_unknown()}`,
        exact: true
      })
    )
    .toBeVisible();
  expect(api.adminCrawler.overview).toHaveBeenLastCalledWith(
    expect.objectContaining({ search: "Municipal", status: "running", view: "active" })
  );
  await expect.element(page.getByRole("alert")).not.toBeInTheDocument();
});

it("serializes refreshes and ignores an old response after filters change", async () => {
  let finish: (value: AdminCrawlerOverview) => void = () => {};
  api.adminCrawler.overview.mockReturnValueOnce(
    new Promise<AdminCrawlerOverview>((resolve) => {
      finish = resolve;
    })
  );
  const intervals = vi.spyOn(globalThis, "setInterval");
  const rendered = show();
  await expect.poll(() => api.adminCrawler.overview.mock.calls.length).toBe(1);
  const poll = intervals.mock.calls.find(([, delay]) => delay === 10_000)?.[0];
  if (typeof poll !== "function") throw new Error("Missing crawler polling callback");
  poll();
  poll();
  await page.getByRole("textbox", { name: m.admin_crawler_search() }).fill("new filter");
  await page.getByRole("button", { name: m.search(), exact: true }).click();
  expect(api.adminCrawler.overview).toHaveBeenCalledTimes(1);
  api.adminCrawler.overview.mockResolvedValueOnce({ ...overview, items: [] });
  finish(overview);
  await expect
    .element(page.getByText(m.admin_crawler_empty_filtered(), { exact: true }))
    .toBeVisible();
  expect(api.adminCrawler.overview).toHaveBeenCalledTimes(2);
  expect(api.adminCrawler.overview).toHaveBeenLastCalledWith(
    expect.objectContaining({ search: "new filter" })
  );
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .not.toBeInTheDocument();
  await rendered.unmount();
  poll();
  expect(api.adminCrawler.overview).toHaveBeenCalledTimes(2);
});

it("clears a filtered empty result and restores the unfiltered query", async () => {
  show();
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .toBeVisible();
  await page.getByRole("textbox", { name: m.admin_crawler_search() }).fill("No match");
  api.adminCrawler.overview.mockResolvedValueOnce({ ...overview, items: [] });
  await page.getByRole("button", { name: m.search(), exact: true }).click();
  await expect
    .element(page.getByText(m.admin_crawler_empty_filtered(), { exact: true }))
    .toBeVisible();
  await page.getByRole("button", { name: m.admin_crawler_clear_filters(), exact: true }).click();
  await expect
    .element(page.getByRole("textbox", { name: m.admin_crawler_search() }))
    .toHaveValue("");
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .toBeVisible();
  expect(api.adminCrawler.overview).toHaveBeenLastCalledWith(
    expect.objectContaining({ search: "", status: undefined, cursor: null, view: "active" })
  );
});

it("pauses polling while hidden and the issue summary opens all tenant warnings", async () => {
  const intervals = vi.spyOn(globalThis, "setInterval");
  show();
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .toBeVisible();
  const poll = intervals.mock.calls.find(([, delay]) => delay === 10_000)?.[0];
  if (typeof poll !== "function") throw new Error("Missing crawler polling callback");
  const visibility = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  poll();
  expect(api.adminCrawler.overview).toHaveBeenCalledTimes(1);
  visibility.mockReturnValue(false);
  poll();
  await expect.poll(() => api.adminCrawler.overview.mock.calls.length).toBe(2);
  await page.getByRole("textbox", { name: m.admin_crawler_search() }).fill("narrow filter");
  await page.getByRole("button", { name: m.search(), exact: true }).click();
  api.adminCrawler.overview.mockResolvedValueOnce({ ...overview, items: [] });
  await page.getByRole("button", { name: m.admin_crawler_show_issues(), exact: true }).click();
  await expect
    .element(page.getByRole("tab", { name: m.admin_crawler_completed_view(), exact: true }))
    .toHaveAttribute("aria-selected", "true");
  await expect
    .element(page.getByRole("textbox", { name: m.admin_crawler_search() }))
    .toHaveValue("");
  expect(api.adminCrawler.overview).toHaveBeenLastCalledWith(
    expect.objectContaining({ view: "recent", status: "issues", search: "", cursor: null })
  );
});

it("paginates bounded results and returns to the first page", async () => {
  api.adminCrawler.overview.mockResolvedValueOnce({ ...overview, next_cursor: "next-page" });
  show();
  await expect.element(page.getByRole("button", { name: m.admin_crawler_next() })).toBeEnabled();
  const second = structuredClone(overview);
  second.items[0].run.id = "run-2";
  second.items[0].website_name = "Another website";
  api.adminCrawler.overview.mockResolvedValueOnce(second);
  await page.getByRole("button", { name: m.admin_crawler_next() }).click();
  await expect
    .element(page.getByRole("button", { name: "Another website", exact: true }))
    .toBeVisible();
  expect(api.adminCrawler.overview).toHaveBeenLastCalledWith(
    expect.objectContaining({ cursor: "next-page", limit: 50 })
  );
  await page.getByRole("button", { name: m.admin_crawler_previous() }).click();
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .toBeVisible();
  expect(api.adminCrawler.overview).toHaveBeenLastCalledWith(
    expect.objectContaining({ cursor: null })
  );
});

it("recovers from an initial load failure and explains an empty active list", async () => {
  api.adminCrawler.overview.mockRejectedValueOnce(new Error("Network unavailable"));
  api.adminCrawler.overview.mockResolvedValue({
    ...overview,
    summary: { ongoing: 0, queued: 0, issues: 0 },
    items: []
  });
  show();
  await expect.element(page.getByRole("alert")).toHaveTextContent(m.admin_crawler_error());
  await page.getByRole("button", { name: m.retry(), exact: true }).click();
  await expect
    .element(page.getByText(m.admin_crawler_empty_active(), { exact: true }))
    .toBeVisible();
  await expect.element(page.getByRole("alert")).not.toBeInTheDocument();
});

it("opens each daily outcome and preserves statistics while loading a new filter", async () => {
  show();
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .toBeVisible();
  await page.getByRole("textbox", { name: m.admin_crawler_search() }).fill("Municipal");
  await page.getByRole("button", { name: m.search(), exact: true }).click();
  let finish: (value: AdminCrawlerOverview) => void = () => {};
  api.adminCrawler.overview.mockReturnValueOnce(
    new Promise<AdminCrawlerOverview>((resolve) => {
      finish = resolve;
    })
  );
  const todayClean = page.getByRole("button", {
    name: m.admin_crawler_show_day_status({
      status: m.admin_crawler_completed_clean(),
      day: m.admin_crawler_today()
    }),
    exact: true
  });
  await todayClean.click();
  await expect.element(todayClean).toBeVisible();
  await expect.element(todayClean).toHaveTextContent("124");
  await expect.element(todayClean).toHaveAccessibleDescription("124");
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .not.toBeInTheDocument();
  expect(api.adminCrawler.overview).toHaveBeenLastCalledWith(
    expect.objectContaining({
      view: "recent",
      period: "today",
      status: "completed",
      search: "",
      cursor: null,
      time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone
    })
  );
  finish({ ...overview, items: [] });
  await expect
    .element(page.getByText(m.admin_crawler_empty_filtered(), { exact: true }))
    .toBeVisible();
  for (const [status, label] of [
    ["partial", m.admin_crawler_with_warnings()],
    ["unsuccessful", m.admin_crawler_unsuccessful()],
    ["cancelled", crawlRunStateLabel("cancelled")]
  ] as const) {
    await page
      .getByRole("button", {
        name: m.admin_crawler_show_day_status({ status: label, day: m.admin_crawler_yesterday() }),
        exact: true
      })
      .click();
    await expect
      .poll(() => api.adminCrawler.overview.mock.lastCall?.[0])
      .toEqual(
        expect.objectContaining({
          view: "recent",
          period: "yesterday",
          status,
          search: "",
          cursor: null
        })
      );
    if (status === "cancelled") {
      await expect
        .element(
          page.getByRole("button", {
            name: m.admin_crawler_show_day_status({
              status: label,
              day: m.admin_crawler_yesterday()
            }),
            exact: true
          })
        )
        .toHaveAccessibleDescription(m.admin_crawler_cancelled_count({ count: "0" }));
    }
  }
});

it("returns to the first history page when a calendar day changes", async () => {
  const intervals = vi.spyOn(globalThis, "setInterval");
  show();
  const dailyButton = page.getByRole("button", {
    name: m.admin_crawler_show_day_status({
      status: m.admin_crawler_completed_clean(),
      day: m.admin_crawler_today()
    }),
    exact: true
  });
  await expect.element(dailyButton).toBeVisible();
  api.adminCrawler.overview.mockResolvedValueOnce({ ...overview, next_cursor: "page-2" });
  await dailyButton.click();
  await page.getByRole("button", { name: m.admin_crawler_next() }).click();
  await expect.element(page.getByRole("button", { name: m.refresh(), exact: true })).toBeEnabled();
  const nextDay = {
    ...overview,
    calendar: { ...overview.calendar, today: { ...overview.calendar.today, date: "2026-09-10" } }
  };
  api.adminCrawler.overview.mockResolvedValue(nextDay);
  const poll = intervals.mock.calls.find(([, delay]) => delay === 10_000)?.[0];
  if (typeof poll !== "function") throw new Error("Missing crawler polling callback");
  const callsBefore = api.adminCrawler.overview.mock.calls.length;
  poll();
  await expect.poll(() => api.adminCrawler.overview.mock.calls.length).toBe(callsBefore + 2);
  expect(api.adminCrawler.overview).toHaveBeenLastCalledWith(
    expect.objectContaining({ period: "today", status: "completed", cursor: null })
  );
  await expect
    .element(page.getByRole("button", { name: m.admin_crawler_previous() }))
    .not.toBeInTheDocument();
});
