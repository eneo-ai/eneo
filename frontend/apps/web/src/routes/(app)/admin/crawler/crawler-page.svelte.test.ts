import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { AdminCrawlerOverview } from "@eneo/eneo-js";
import "../../../../app.css";
import { m } from "$lib/paraglide/messages";

const api = vi.hoisted(() => ({
  adminCrawler: { overview: vi.fn(), failures: vi.fn() },
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

beforeEach(async () => {
  document.documentElement.dataset.theme = "light";
  await page.viewport(1180, 900);
  vi.clearAllMocks();
  api.adminCrawler.overview.mockResolvedValue(structuredClone(overview));
});

afterEach(() => vi.restoreAllMocks());

function show() {
  const result = render(CrawlerPage);
  result.container.style.cssText =
    "position: relative; z-index: 10; display: flex; height: 100dvh; width: 100%;";
  return result;
}

it("shows tenant crawl metadata and opens failures through the admin endpoint", async () => {
  api.adminCrawler.failures.mockResolvedValue({
    run: overview.items[0].run,
    items: [],
    total_count: 0,
    next_cursor: null,
    details_available: true
  });
  show();
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .toBeVisible();
  await expect.element(page.getByText("Communications", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Municipal website", exact: true }).click();
  await expect.poll(() => api.adminCrawler.failures.mock.calls.length).toBe(1);
  expect(api.websites.crawlRuns.failures).not.toHaveBeenCalled();
  await userEvent.keyboard("{Escape}");
  await expect
    .element(page.getByRole("button", { name: "Municipal website", exact: true }))
    .toHaveFocus();
});

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
  await expect.element(page.getByRole("alert")).toHaveTextContent(m.admin_crawler_error());
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
  api.adminCrawler.overview.mockResolvedValueOnce(updated);
  await page.getByRole("button", { name: m.retry(), exact: true }).click();
  await expect
    .element(page.getByText(m.pages_succeeded({ count: 8 }), { exact: true }))
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
    .element(page.getByRole("tab", { name: m.admin_crawler_last_day(), exact: true }))
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
