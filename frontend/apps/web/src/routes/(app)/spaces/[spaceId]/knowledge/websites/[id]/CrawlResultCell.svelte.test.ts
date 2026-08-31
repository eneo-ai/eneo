import type { CrawlRun } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import CrawlResultCell from "./CrawlResultCell.svelte";

function crawlRun(overrides: Partial<CrawlRun> = {}): CrawlRun {
  return {
    id: crypto.randomUUID(),
    pages_crawled: null,
    files_downloaded: null,
    pages_failed: null,
    files_failed: null,
    status: "queued",
    phase: "queued",
    outcome: null,
    origin: "manual",
    result_location: null,
    finished_at: null,
    failure_code: null,
    failure_detail: null,
    cancel_requested_at: null,
    attempt_count: 1,
    ...overrides
  };
}

describe("CrawlResultCell", () => {
  it("updates result counters when polling replaces a queued crawl", async () => {
    const rendered = render(CrawlResultCell, { crawl: crawlRun() });

    await expect.element(page.getByText(m.queued(), { exact: true })).toBeVisible();

    await rendered.rerender({
      crawl: crawlRun({
        pages_crawled: 5,
        files_downloaded: 2,
        pages_failed: 1,
        files_failed: 0,
        status: "complete",
        phase: "terminal",
        outcome: "partial",
        finished_at: new Date().toISOString()
      })
    });

    await expect
      .element(page.getByText(m.pages_and_files_succeeded({ pages: 5, files: 2 }), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.pages_failed({ count: 1 }), { exact: true }))
      .toBeVisible();
  });

  it("shows stopping and cancelled states instead of treating them as running", async () => {
    const rendered = render(CrawlResultCell, {
      crawl: crawlRun({ phase: "stopping", status: "in progress" })
    });

    await expect.element(page.getByText(m.crawl_status_stopping(), { exact: true })).toBeVisible();

    await rendered.rerender({
      crawl: crawlRun({
        phase: "terminal",
        outcome: "cancelled",
        status: "failed",
        failure_code: "cancelled"
      })
    });

    await expect.element(page.getByText(m.crawl_status_cancelled(), { exact: true })).toBeVisible();
  });

  it("shows persisted counters while a crawl is running", async () => {
    render(CrawlResultCell, {
      crawl: crawlRun({
        phase: "running",
        status: "in progress",
        pages_crawled: 12,
        files_downloaded: 2,
        pages_failed: 1,
        files_failed: 0
      })
    });

    await expect
      .element(
        page.getByText(m.pages_and_files_succeeded({ pages: 12, files: 2 }), { exact: true })
      )
      .toBeVisible();
    await expect
      .element(page.getByText(m.pages_failed({ count: 1 }), { exact: true }))
      .toBeVisible();
  });

  it("turns legacy internal crawler reasons into human-readable guidance", async () => {
    render(CrawlResultCell, {
      crawl: crawlRun({
        phase: "terminal",
        outcome: "partial",
        status: "complete",
        pages_crawled: 507,
        pages_failed: 6,
        failure_summary: { _RedirectRejected: 6 }
      })
    });

    await page.getByText(m.pages_failed({ count: 6 }), { exact: true }).hover();
    await expect
      .element(
        page.getByText("Omdirigeringen ledde utanför den tillåtna webbplatsen: 6", {
          exact: false
        })
      )
      .toBeVisible();
    await expect
      .element(page.getByText("_RedirectRejected", { exact: false }))
      .not.toBeInTheDocument();
  });
});
