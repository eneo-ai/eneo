import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import type {
  CrawlerTenantWebsiteProcessingAggregateItem,
  CrawlerTenantWebsiteProcessingAggregateResponse
} from "./crawlerWebsiteProcessing";
import {
  CRAWLER_LOW_RETENTION_THRESHOLD,
  CRAWLER_SOURCE_SKIP_DRIFT_MIN_INDEXED,
  getCrawlerWebsiteProcessingCostLabel,
  getCrawlerWebsiteProcessingFailureLabel,
  getCrawlerWebsiteProcessingFetchedLabel,
  getCrawlerWebsiteProcessingRetainedLabel,
  getCrawlerWebsiteProcessingTotalLabel,
  getCrawlerWebsiteProcessingWebsiteLabel,
  isCrawlerWebsiteProcessingLowRetention,
  isCrawlerWebsiteProcessingSourceSkipDrift
} from "./crawlerWebsiteProcessing";

overwriteGetLocale(() => "en");

const aggregate: CrawlerTenantWebsiteProcessingAggregateResponse = {
  items: [],
  total: 12,
  limit: 5,
  offset: 0,
  days: 7,
  since: "2026-05-08T12:00:00Z",
  until: "2026-05-15T12:00:00Z"
};

const item: CrawlerTenantWebsiteProcessingAggregateItem = {
  website_id: "12345678-1234-4234-8234-123456789abc",
  website_name: "Municipality site",
  total_runs: 4,
  terminal_runs: 4,
  failed_runs: 1,
  pages_crawled: 10,
  files_downloaded: 2,
  pages_hash_retained: 290,
  files_hash_retained: 3,
  pages_source_retained: 20,
  files_too_large_skipped: 7,
  pages_failed: 1,
  files_failed: 2,
  update_interval: "daily",
  schedule_frequency_weight: 7,
  indexed_content_count: 325,
  retention_rate: 313 / 325,
  cost_pressure_score: 84
};

test("website processing labels keep crawler cost and retention readable", () => {
  expect(
    getCrawlerWebsiteProcessingTotalLabel({
      ...aggregate,
      items: [item]
    })
  ).toBe("Showing 1 of 12 websites from the last 7 days");
  expect(getCrawlerWebsiteProcessingWebsiteLabel(item)).toBe("Municipality site");
  expect(getCrawlerWebsiteProcessingFetchedLabel(item)).toBe("10 pages · 2 files");
  expect(getCrawlerWebsiteProcessingCostLabel(item)).toBe("Daily · score 84 · 96% retained");
  expect(getCrawlerWebsiteProcessingRetainedLabel(item)).toBe("313 retained · 7 too large");
  expect(getCrawlerWebsiteProcessingFailureLabel(item)).toBe("Failed runs: 1 · failed items: 3");
});

test("website processing labels handle unnamed and healthy websites", () => {
  expect(
    getCrawlerWebsiteProcessingWebsiteLabel({
      ...item,
      website_name: null
    })
  ).toBe("Website 12345678");
  expect(
    getCrawlerWebsiteProcessingFailureLabel({
      ...item,
      failed_runs: 0,
      pages_failed: 0,
      files_failed: 0
    })
  ).toBeNull();
  expect(
    getCrawlerWebsiteProcessingCostLabel({
      ...item,
      update_interval: null,
      cost_pressure_score: 0
    })
  ).toBe("Unknown schedule · score 0 · 96% retained");
});

test("low-retention drift signal flags websites below the operator-visible waste threshold", () => {
  // Healthy retention (96%) stays unflagged so operators don't drown in
  // false positives on well-behaving websites.
  expect(isCrawlerWebsiteProcessingLowRetention(item)).toBe(false);

  // Cold websites with no indexed work are idle, not wasteful.
  expect(
    isCrawlerWebsiteProcessingLowRetention({
      ...item,
      indexed_content_count: 0,
      retention_rate: 0
    })
  ).toBe(false);

  // Just below the threshold flags as wasteful.
  expect(
    isCrawlerWebsiteProcessingLowRetention({
      ...item,
      retention_rate: CRAWLER_LOW_RETENTION_THRESHOLD - 0.01
    })
  ).toBe(true);

  // At threshold is not "below threshold" — the operator copy says
  // "below 50%" so the threshold itself is acceptable.
  expect(
    isCrawlerWebsiteProcessingLowRetention({
      ...item,
      retention_rate: CRAWLER_LOW_RETENTION_THRESHOLD
    })
  ).toBe(false);
});

test("source-skip drift signal flags busy websites where sitemap lastmod stopped helping", () => {
  // Busy + retained pages via source-skip = healthy.
  expect(isCrawlerWebsiteProcessingSourceSkipDrift(item)).toBe(false);

  // Busy + zero source-retained = drift.
  expect(
    isCrawlerWebsiteProcessingSourceSkipDrift({
      ...item,
      indexed_content_count: CRAWLER_SOURCE_SKIP_DRIFT_MIN_INDEXED,
      pages_source_retained: 0
    })
  ).toBe(true);

  // Quiet websites with zero source-retained are not drift — there
  // isn't enough work to compare. Avoids noisy flags on barely-used
  // websites that the operator can't act on anyway.
  expect(
    isCrawlerWebsiteProcessingSourceSkipDrift({
      ...item,
      indexed_content_count: CRAWLER_SOURCE_SKIP_DRIFT_MIN_INDEXED - 1,
      pages_source_retained: 0
    })
  ).toBe(false);
});
