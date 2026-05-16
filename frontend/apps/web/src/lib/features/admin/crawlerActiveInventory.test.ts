import { IntricError } from "@intric/intric-js";
import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import type { CrawlerActiveInventoryItem } from "./crawlerActiveInventory";
import {
  CRAWLER_ACTIVE_INVENTORY_DEFAULTS,
  CRAWLER_ACTIVE_INVENTORY_LIFECYCLE_FILTER_OPTIONS,
  CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES,
  canAbortCrawlerActiveInventoryItem,
  getCrawlerAbortConflictMessage,
  getCrawlerActiveInventoryLifecycleFilterLabel,
  getCrawlerActiveInventoryResultLabels,
  getCrawlerActiveInventorySourceLabel,
  getCrawlerActiveInventoryStartedByLabel,
  getCrawlerActiveInventoryStatusLabel,
  getCrawlerActiveInventoryWebsiteLabel,
  isCrawlerActiveInventoryPageSize,
  offsetFromCrawlerActiveInventoryPage,
  pageFromCrawlerActiveInventoryOffset
} from "./crawlerActiveInventory";

overwriteGetLocale(() => "en");

const baseActiveItem: CrawlerActiveInventoryItem = {
  job_id: "11111111-1111-4111-8111-111111111111",
  crawl_run_id: "22222222-2222-4222-8222-222222222222",
  website_id: "12345678-1234-4234-8234-123456789abc",
  website_name: null,
  space_id: null,
  space_name: null,
  collection_id: null,
  collection_name: null,
  user_started_by_id: null,
  user_started_by_email: null,
  update_interval: null,
  tenant_id: "33333333-3333-4333-8333-333333333333",
  tenant_display_name: "Tenant",
  status: "in progress",
  lifecycle_state: "running_with_progress",
  is_abortable: false,
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

test("abortability follows backend is_abortable flag, not lifecycle state", () => {
  expect(
    canAbortCrawlerActiveInventoryItem({
      ...baseActiveItem,
      lifecycle_state: "queued",
      is_abortable: true
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
  expect(
    canAbortCrawlerActiveInventoryItem({
      ...baseActiveItem,
      lifecycle_state: "queued",
      is_abortable: false
    })
  ).toBe(false);
});

test("abort conflict messages use typed backend conflict codes", () => {
  // Running aborts no longer return RUNNING_ABORT_NOT_IMPLEMENTED — the
  // backend now commits a terminal CRAWL_ABORTED event for queued and
  // running crawls alike. Only CRAWL_NOT_ABORTABLE remains as a typed
  // conflict (job finished or transitioned to a non-abortable status
  // between status check and terminal commit).
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

test("active inventory source label combines space and collection with separator", () => {
  expect(
    getCrawlerActiveInventorySourceLabel({
      ...baseActiveItem,
      space_name: "Marketing",
      collection_name: "Brand knowledge"
    })
  ).toBe("Marketing › Brand knowledge");
});

test("active inventory source label falls back to whichever attribution is set", () => {
  expect(
    getCrawlerActiveInventorySourceLabel({
      ...baseActiveItem,
      space_name: "Marketing",
      collection_name: null
    })
  ).toBe("Marketing");
  expect(
    getCrawlerActiveInventorySourceLabel({
      ...baseActiveItem,
      space_name: null,
      collection_name: "Brand knowledge"
    })
  ).toBe("Brand knowledge");
  expect(getCrawlerActiveInventorySourceLabel(baseActiveItem)).toBeNull();
});

test("active inventory started-by label returns trimmed email or null", () => {
  expect(
    getCrawlerActiveInventoryStartedByLabel({
      ...baseActiveItem,
      user_started_by_email: "owner@example.com"
    })
  ).toBe("owner@example.com");
  expect(
    getCrawlerActiveInventoryStartedByLabel({
      ...baseActiveItem,
      user_started_by_email: "   "
    })
  ).toBeNull();
  expect(getCrawlerActiveInventoryStartedByLabel(baseActiveItem)).toBeNull();
});

test("lifecycle filter options cover all and the three active buckets exhaustively", () => {
  expect(CRAWLER_ACTIVE_INVENTORY_LIFECYCLE_FILTER_OPTIONS).toEqual([
    "all",
    "queued",
    "running_with_progress",
    "running_no_progress"
  ]);
  expect(getCrawlerActiveInventoryLifecycleFilterLabel("all")).toBe("All");
  expect(getCrawlerActiveInventoryLifecycleFilterLabel("queued")).toBe("Queued");
  expect(getCrawlerActiveInventoryLifecycleFilterLabel("running_with_progress")).toBe(
    "Running with progress"
  );
  expect(getCrawlerActiveInventoryLifecycleFilterLabel("running_no_progress")).toBe(
    "Running, waiting for progress"
  );
});

test("page size options expose 25/50/100 and the default matches the first option", () => {
  // The backend accepts up to limit=200, but the UI keeps the choices
  // small so the page-size selector stays a quick keyboard-toggle, not a
  // free numeric input. 25 is the default because it fits a 1080p screen
  // without scrolling; 50/100 unblock operators with hundreds of crawls
  // who would otherwise paginate 25 rows at a time.
  expect(CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES).toEqual([25, 50, 100]);
  expect(CRAWLER_ACTIVE_INVENTORY_DEFAULTS.limit).toBe(CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES[0]);
  expect(isCrawlerActiveInventoryPageSize(25)).toBe(true);
  expect(isCrawlerActiveInventoryPageSize(50)).toBe(true);
  expect(isCrawlerActiveInventoryPageSize(100)).toBe(true);
  // Numbers outside the curated list must not round-trip through the
  // selector — they could come from a stale URL query string and would
  // otherwise let the operator hit the 200 cap without warning.
  expect(isCrawlerActiveInventoryPageSize(40)).toBe(false);
  expect(isCrawlerActiveInventoryPageSize(0)).toBe(false);
  expect(isCrawlerActiveInventoryPageSize(-1)).toBe(false);
});

test("offset / page conversion is invertible across the typical ranges", () => {
  for (const pageSize of CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES) {
    for (const page of [1, 2, 5, 10]) {
      const offset = offsetFromCrawlerActiveInventoryPage(page, pageSize);
      expect(pageFromCrawlerActiveInventoryOffset(offset, pageSize)).toBe(page);
    }
  }
});

test("page-from-offset normalizes degenerate inputs to page 1", () => {
  // Out-of-band values can land here via URL query strings or a stale
  // bookmark. Page 1 is the safe fallback — never zero or negative,
  // since the pagination component treats page < 1 as an unbounded back
  // arrow.
  expect(pageFromCrawlerActiveInventoryOffset(0, 25)).toBe(1);
  expect(pageFromCrawlerActiveInventoryOffset(-5, 25)).toBe(1);
  expect(pageFromCrawlerActiveInventoryOffset(24, 25)).toBe(1);
  expect(pageFromCrawlerActiveInventoryOffset(25, 25)).toBe(2);
  expect(pageFromCrawlerActiveInventoryOffset(60, 25)).toBe(3);
  expect(pageFromCrawlerActiveInventoryOffset(100, 0)).toBe(1);
});

test("offset-from-page clamps page < 1 to offset 0", () => {
  // bits-ui's pagination primitive can emit page=0 during boundary
  // transitions; clamping prevents an offset=-25 round-trip to the
  // backend (which would 422).
  expect(offsetFromCrawlerActiveInventoryPage(1, 25)).toBe(0);
  expect(offsetFromCrawlerActiveInventoryPage(0, 25)).toBe(0);
  expect(offsetFromCrawlerActiveInventoryPage(-1, 25)).toBe(0);
  expect(offsetFromCrawlerActiveInventoryPage(2, 25)).toBe(25);
  expect(offsetFromCrawlerActiveInventoryPage(4, 50)).toBe(150);
});
