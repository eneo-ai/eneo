import { IntricError } from "@intric/intric-js";
import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import type { CrawlerActiveInventoryItem } from "./crawlerActiveInventory";
import {
  canAbortCrawlerActiveInventoryItem,
  getCrawlerAbortConflictMessage,
  getCrawlerActiveInventoryResultLabels,
  getCrawlerActiveInventoryStatusLabel,
  getCrawlerActiveInventoryWebsiteLabel
} from "./crawlerActiveInventory";

overwriteGetLocale(() => "en");

const baseActiveItem: CrawlerActiveInventoryItem = {
  job_id: "11111111-1111-4111-8111-111111111111",
  crawl_run_id: "22222222-2222-4222-8222-222222222222",
  website_id: "12345678-1234-4234-8234-123456789abc",
  website_name: null,
  tenant_id: "33333333-3333-4333-8333-333333333333",
  tenant_display_name: "Tenant",
  status: "in progress",
  lifecycle_state: "running_with_progress",
  job_created_at: "2026-05-12T14:14:32.000Z",
  job_updated_at: "2026-05-12T14:14:50.000Z",
  crawl_run_created_at: "2026-05-12T14:14:33.000Z",
  pages_crawled: 300,
  files_downloaded: 1,
  pages_failed: 0,
  files_failed: 0,
  pages_source_retained: 11,
  pages_hash_retained: 290,
  files_hash_retained: 1,
  files_too_large_skipped: 12
};

test("active crawler labels use stable website fallback and lifecycle copy", () => {
  expect(getCrawlerActiveInventoryWebsiteLabel(baseActiveItem)).toBe("Website 12345678");
  expect(getCrawlerActiveInventoryStatusLabel(baseActiveItem)).toBe("Running with progress");
  expect(
    getCrawlerActiveInventoryStatusLabel({
      ...baseActiveItem,
      lifecycle_state: "queued"
    })
  ).toBe("Queued");
  expect(
    getCrawlerActiveInventoryStatusLabel({
      ...baseActiveItem,
      lifecycle_state: "running_no_progress"
    })
  ).toBe("Running, waiting for progress");
  expect(
    getCrawlerActiveInventoryStatusLabel({
      ...baseActiveItem,
      lifecycle_state: "terminal"
    })
  ).toBe("No longer active");
});

test("active crawler labels prefer stored website names", () => {
  expect(
    getCrawlerActiveInventoryWebsiteLabel({
      ...baseActiveItem,
      website_name: "Hudiksvall preschool"
    })
  ).toBe("Hudiksvall preschool");
});

test("active crawler result labels distinguish fetched, retained, source-skipped and large files", () => {
  expect(getCrawlerActiveInventoryResultLabels(baseActiveItem).map((label) => label.label)).toEqual(
    [
      "Fetched 300 pages and 1 file",
      "Indexed 10 pages",
      "Unchanged: 290 pages and 1 file",
      "Download skipped: 11 pages",
      "Too large: 12 files"
    ]
  );
});

test("queued orphan-like item falls back to job id when website is absent", () => {
  expect(
    getCrawlerActiveInventoryWebsiteLabel({
      ...baseActiveItem,
      crawl_run_id: null,
      website_id: null,
      website_name: null,
      lifecycle_state: "queued"
    })
  ).toBe("Crawler job 11111111");
});

test("only queued crawler jobs are abortable from the admin inventory", () => {
  expect(
    canAbortCrawlerActiveInventoryItem({
      ...baseActiveItem,
      lifecycle_state: "queued"
    })
  ).toBe(true);
  expect(canAbortCrawlerActiveInventoryItem(baseActiveItem)).toBe(false);
  expect(
    canAbortCrawlerActiveInventoryItem({
      ...baseActiveItem,
      lifecycle_state: "terminal"
    })
  ).toBe(false);
  expect(
    canAbortCrawlerActiveInventoryItem({
      ...baseActiveItem,
      lifecycle_state: "running_no_progress"
    })
  ).toBe(false);
});

test("abort conflict messages use typed backend conflict codes", () => {
  expect(
    getCrawlerAbortConflictMessage(
      new IntricError(
        "Conflict",
        "RESPONSE",
        409,
        0,
        {
          error_code: "RUNNING_ABORT_NOT_IMPLEMENTED",
          detail: "Running crawl abort is not implemented yet."
        },
        { endpoint: "POST@/api/v1/admin/crawler/jobs/id/abort" }
      )
    )
  ).toBe("Running crawls cannot be cancelled from this page yet.");

  expect(
    getCrawlerAbortConflictMessage(
      new IntricError(
        "Conflict",
        "RESPONSE",
        409,
        0,
        {
          error_code: "CRAWL_NOT_ABORTABLE",
          detail: "The crawl job is no longer abortable."
        },
        { endpoint: "POST@/api/v1/admin/crawler/jobs/id/abort" }
      )
    )
  ).toBe("This crawler job can no longer be cancelled. Refreshing status.");
});
