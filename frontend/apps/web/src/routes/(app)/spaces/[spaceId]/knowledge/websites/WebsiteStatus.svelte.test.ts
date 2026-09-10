import type { CrawlRun, WebsiteSparse } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import WebsiteStatus from "./WebsiteStatus.svelte";

it("updates website status when refreshed knowledge replaces its latest crawl", async () => {
  const run: CrawlRun = {
    id: "run-1",
    pages_crawled: 0,
    pages_failed: 0,
    files_downloaded: 0,
    files_failed: 0,
    phase: "queued",
    status: "queued",
    outcome: null,
    origin: "manual",
    result_location: null,
    finished_at: null,
    failure_code: null,
    failure_detail: null,
    cancel_requested_at: null,
    attempt_count: 1
  };
  const website = { id: "website-1", latest_crawl: run } as WebsiteSparse;
  const onshowFailures = vi.fn();
  const rendered = render(WebsiteStatus, { website, onshowFailures });
  await expect.element(page.getByText(m.queued(), { exact: true })).toBeVisible();

  await rendered.rerender({
    website: {
      ...website,
      latest_crawl: { ...run, phase: "running", status: "in progress" }
    }
  });
  await expect.element(page.getByText(m.in_progress(), { exact: true })).toBeVisible();

  await rendered.rerender({
    website: {
      ...website,
      latest_crawl: {
        ...run,
        phase: "terminal",
        status: "failed",
        outcome: "failed",
        failure_code: "tenant_quota_exceeded"
      }
    }
  });
  await expect.element(page.getByText(m.failed(), { exact: true })).toBeVisible();
  await page.getByRole("button", { name: m.crawl_view_errors() }).click();
  expect(onshowFailures).toHaveBeenLastCalledWith(null);

  await rendered.rerender({
    website: {
      ...website,
      latest_crawl: {
        ...run,
        phase: "terminal",
        status: "complete",
        outcome: "partial",
        finished_at: "2026-09-09T12:00:00Z",
        pages_crawled: 12,
        pages_failed: 2,
        failure_code: "processing_failed"
      }
    }
  });
  await page.getByRole("button", { name: m.crawl_view_failed_pages({ count: 2 }) }).click();
  expect(onshowFailures).toHaveBeenLastCalledWith("page");
  await page.getByText(m.crawl_completed_with_warnings(), { exact: true }).hover();
  const tooltip = page.getByRole("tooltip");
  await expect.element(tooltip).toHaveTextContent(m.pages_failed({ count: "2" }));
  await expect.element(tooltip).toHaveTextContent(m.crawl_failure_partial());
});
