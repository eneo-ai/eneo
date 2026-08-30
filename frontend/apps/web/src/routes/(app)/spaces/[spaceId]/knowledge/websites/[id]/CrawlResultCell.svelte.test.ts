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
      .element(page.getByText(m.crawled_pages_and_files({ pages: 5, files: 2 }), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.pages_failed({ count: 1 }), { exact: true }))
      .toBeVisible();
  });
});
