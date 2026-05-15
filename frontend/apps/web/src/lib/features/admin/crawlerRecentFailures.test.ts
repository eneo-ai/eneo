import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import type { CrawlerRecentFailureItem } from "./crawlerRecentFailures";
import {
  getCrawlerRecentFailureOutcomeLabel,
  getCrawlerRecentFailureResultLabels,
  getCrawlerRecentFailureWebsiteLabel
} from "./crawlerRecentFailures";

overwriteGetLocale(() => "en");

const baseFailure: CrawlerRecentFailureItem = {
  crawl_run_id: "22222222-2222-4222-8222-222222222222",
  job_id: "11111111-1111-4111-8111-111111111111",
  website_id: "12345678-1234-4234-8234-123456789abc",
  website_name: null,
  tenant_id: "33333333-3333-4333-8333-333333333333",
  tenant_display_name: "Tenant",
  outcome_code: "CRAWL_RUNTIME_TIMEOUT",
  failure_summary: { EMPTY_CONTENT: 1 },
  finished_at: "2026-05-12T14:14:50.000Z",
  pages_crawled: 300,
  files_downloaded: 1,
  pages_failed: 1,
  files_failed: 0,
  pages_source_retained: 0,
  pages_hash_retained: 290,
  files_hash_retained: 1,
  files_too_large_skipped: 12
};

test("recent crawler failure labels use typed outcome text and stable website fallback", () => {
  expect(getCrawlerRecentFailureOutcomeLabel(baseFailure)).toBe(
    "The crawl ran too long and was stopped"
  );
  expect(getCrawlerRecentFailureWebsiteLabel(baseFailure)).toBe("Website 12345678");
});

test("recent crawler failure result labels distinguish work, retained content, size skips, and failures", () => {
  expect(getCrawlerRecentFailureResultLabels(baseFailure).map((label) => label.label)).toEqual([
    "Fetched 300 pages and 1 file",
    "Indexed 9 pages",
    "Unchanged: 290 pages and 1 file",
    "Too large: 12 files",
    "Failed: 1 page"
  ]);
});

test("recent crawler failure prefers stored website names", () => {
  expect(
    getCrawlerRecentFailureWebsiteLabel({
      ...baseFailure,
      website_name: "Hudiksvall preschool"
    })
  ).toBe("Hudiksvall preschool");
});
