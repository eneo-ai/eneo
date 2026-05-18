import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import type {
  CrawlerTenantWebsiteProcessingAggregateItem,
  CrawlerTenantWebsiteProcessingAggregateResponse
} from "./crawlerWebsiteProcessing";
import {
  CRAWLER_LOW_RETENTION_THRESHOLD,
  CRAWLER_SOURCE_SKIP_DRIFT_MIN_INDEXED,
  getCrawlerWebsiteProcessingEmbeddingUsageLabel,
  getCrawlerWebsiteProcessingFailureLabel,
  getCrawlerWebsiteProcessingFetchedLabel,
  getCrawlerWebsiteProcessingHealthSignal,
  getCrawlerWebsiteProcessingIndexedSizeLabel,
  getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel,
  getCrawlerWebsiteProcessingLatestRunModelLabel,
  getCrawlerWebsiteProcessingLatestRunProviderLabel,
  getCrawlerWebsiteProcessingLatestRunUsageSourceLabel,
  getCrawlerWebsiteProcessingLoadPressureLabel,
  getCrawlerWebsiteProcessingOwnerLabel,
  getCrawlerWebsiteProcessingRetainedLabel,
  getCrawlerWebsiteProcessingReuseLabel,
  getCrawlerWebsiteProcessingScheduleLabel,
  getCrawlerWebsiteProcessingSpaceLabel,
  getCrawlerWebsiteProcessingTotalLabel,
  getCrawlerWebsiteProcessingUrlLabel,
  getCrawlerWebsiteProcessingWebsiteLabel,
  isCrawlerWebsiteProcessingLowRetention,
  isCrawlerWebsiteProcessingSourceSkipDrift
} from "./crawlerWebsiteProcessing";

overwriteGetLocale(() => "en");

const aggregate: CrawlerTenantWebsiteProcessingAggregateResponse = {
  items: [],
  summary: {
    website_count: 12,
    total_runs: 20,
    terminal_runs: 18,
    failed_runs: 2,
    pages_crawled: 120,
    files_downloaded: 12,
    retained_content_count: 313,
    files_too_large_skipped: 7,
    failed_item_count: 3,
    indexed_size_bytes: 123456,
    embedding_input_tokens: 12345,
    embedding_total_cost_usd: "0.001234000000",
    action_required_count: 4
  },
  space_rollup: [
    {
      space_id: "22345678-1234-4234-8234-123456789abc",
      space_name: "Governance",
      website_count: 2,
      total_runs: 4,
      pages_crawled: 10,
      files_downloaded: 2,
      indexed_size_bytes: 123456,
      embedding_input_tokens: 12345,
      embedding_total_cost_usd: "0.001234000000",
      action_required_count: 1,
      latest_run_at: "2026-05-15T11:30:00Z"
    }
  ],
  total: 12,
  limit: 5,
  offset: 0,
  days: 7,
  since: "2026-05-08T12:00:00Z",
  until: "2026-05-15T12:00:00Z",
  low_retention_threshold: 0.5,
  source_skip_drift_min_indexed: 50
};

const item: CrawlerTenantWebsiteProcessingAggregateItem = {
  website_id: "12345678-1234-4234-8234-123456789abc",
  website_name: "Municipality site",
  website_url: "https://municipality.example.com",
  space_id: "22345678-1234-4234-8234-123456789abc",
  space_name: "Governance",
  collection_id: "32345678-1234-4234-8234-123456789abc",
  collection_name: "Schools",
  owner_user_id: "42345678-1234-4234-8234-123456789abc",
  owner_email: "owner@example.com",
  indexed_size_bytes: 123456,
  latest_run_at: "2026-05-15T11:30:00Z",
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
  cost_pressure_score: 84,
  embedding_input_tokens: 12345,
  embedding_total_cost_usd: "0.001234000000",
  latest_embedding_model_name_snapshot: "text-embedding-3-small",
  latest_embedding_model_litellm_name_snapshot: "openai/text-embedding-3-small",
  latest_embedding_model_provider_snapshot: "openai",
  latest_embedding_input_tokens: 2345,
  latest_embedding_total_cost_usd: "0.000234000000",
  latest_embedding_usage_source: "provider_reported"
};

test("website processing labels keep crawler load and retention readable", () => {
  expect(
    getCrawlerWebsiteProcessingTotalLabel({
      ...aggregate,
      items: [item]
    })
  ).toBe("Showing 1 of 12 websites from the last 7 days");
  expect(getCrawlerWebsiteProcessingWebsiteLabel(item)).toBe("Municipality site");
  expect(getCrawlerWebsiteProcessingUrlLabel(item)).toBe("https://municipality.example.com");
  expect(getCrawlerWebsiteProcessingOwnerLabel(item)).toBe("owner@example.com");
  expect(getCrawlerWebsiteProcessingSpaceLabel(item)).toBe("Governance › Schools");
  expect(getCrawlerWebsiteProcessingScheduleLabel(item)).toBe("Daily");
  expect(getCrawlerWebsiteProcessingIndexedSizeLabel(item)).toBe("120.6 KiB");
  expect(getCrawlerWebsiteProcessingFetchedLabel(item)).toBe("10 pages · 2 files");
  expect(getCrawlerWebsiteProcessingReuseLabel(item)).toBe("96% reused");
  expect(getCrawlerWebsiteProcessingLoadPressureLabel(item)).toBe(
    "Daily · priority 84 · 96% reused"
  );
  expect(getCrawlerWebsiteProcessingEmbeddingUsageLabel(item)).toBe("12,345 tokens · $0.001234");
  expect(getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel(item)).toBe(
    "2,345 tokens · $0.000234"
  );
  expect(getCrawlerWebsiteProcessingLatestRunModelLabel(item)).toBe("text-embedding-3-small");
  expect(getCrawlerWebsiteProcessingLatestRunProviderLabel(item)).toBe("openai");
  expect(getCrawlerWebsiteProcessingLatestRunUsageSourceLabel(item)).toBe("Provider reported");
  expect(getCrawlerWebsiteProcessingRetainedLabel(item)).toBe("313 reused · 7 too large");
  expect(getCrawlerWebsiteProcessingFailureLabel(item)).toBe("Failed runs: 1 · failed items: 3");
  expect(getCrawlerWebsiteProcessingHealthSignal(item)).toMatchObject({
    state: "failure",
    label: "Failure"
  });
});

test("website processing labels handle unnamed and healthy websites", () => {
  expect(
    getCrawlerWebsiteProcessingWebsiteLabel({
      ...item,
      website_name: null
    })
  ).toBe("https://municipality.example.com");
  expect(
    getCrawlerWebsiteProcessingWebsiteLabel({
      ...item,
      website_name: null,
      website_url: ""
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
    getCrawlerWebsiteProcessingLoadPressureLabel({
      ...item,
      update_interval: null,
      cost_pressure_score: 0
    })
  ).toBe("Unknown schedule · priority 0 · 96% reused");
  expect(
    getCrawlerWebsiteProcessingEmbeddingUsageLabel({
      ...item,
      embedding_input_tokens: null,
      embedding_total_cost_usd: null
    })
  ).toBe("Missing for this run");
  expect(
    getCrawlerWebsiteProcessingEmbeddingUsageLabel({
      ...item,
      embedding_total_cost_usd: null
    })
  ).toBe("12,345 tokens · cost not recorded");
  expect(
    getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel({
      ...item,
      latest_embedding_input_tokens: 0,
      latest_embedding_total_cost_usd: null
    })
  ).toBe("0 tokens · nothing new embedded");
  expect(
    getCrawlerWebsiteProcessingLatestRunModelLabel({
      ...item,
      latest_embedding_model_name_snapshot: null,
      latest_embedding_model_litellm_name_snapshot: null
    })
  ).toBe("Not recorded for older runs");
  expect(
    getCrawlerWebsiteProcessingLatestRunUsageSourceLabel({
      ...item,
      latest_embedding_usage_source: "missing"
    })
  ).toBe("Token usage missing");
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
