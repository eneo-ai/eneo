import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import type { CrawlerFailureClusterItem } from "./crawlerFailureClusters";
import {
  getCrawlerFailureClusterAttributionLabel,
  getCrawlerFailureClusterOccurrenceLabel,
  getCrawlerFailureClusterWebsiteLabel,
  getCrawlerFailureClusterWorkLabel
} from "./crawlerFailureClusters";

overwriteGetLocale(() => "en");

const baseCluster: CrawlerFailureClusterItem = {
  website_id: "12345678-1234-4234-8234-123456789abc",
  website_url: "https://example.com",
  website_name: null,
  space_id: "22345678-1234-4234-8234-123456789abc",
  space_name: "Public services",
  owner_user_id: "32345678-1234-4234-8234-123456789abc",
  owner_email: "owner@example.com",
  outcome_code: "CRAWL_RUNTIME_TIMEOUT",
  outcome_category: "timeout",
  occurrences: 5,
  watchdog_occurrences: 5,
  first_failed_at: "2026-05-17T08:28:00Z",
  latest_failed_at: "2026-05-17T10:28:00Z",
  sample_crawl_run_id: "42345678-1234-4234-8234-123456789abc",
  pages_crawled: 0,
  files_downloaded: 0,
  pages_failed: 0,
  files_failed: 0
};

test("failure cluster labels explain repeated watchdog failures without raw counters when no content was fetched", () => {
  expect(getCrawlerFailureClusterWebsiteLabel(baseCluster)).toBe("https://example.com");
  expect(getCrawlerFailureClusterAttributionLabel(baseCluster)).toBe(
    "Public services · owner@example.com"
  );
  expect(getCrawlerFailureClusterOccurrenceLabel(baseCluster)).toBe("5 times · 5 watchdog stops");
  expect(getCrawlerFailureClusterWorkLabel(baseCluster)).toBe("No content was fetched");
});

test("failure cluster work label includes fetched and failed objects when present", () => {
  expect(
    getCrawlerFailureClusterWorkLabel({
      ...baseCluster,
      pages_crawled: 12,
      files_downloaded: 3,
      pages_failed: 1,
      files_failed: 2
    })
  ).toBe("12 pages · 3 files · 3 failed objects");
});
