import type { components } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";
import {
  formatCrawlerCount,
  formatCrawlerDecimal,
  formatCrawlerPercent,
  formatCrawlerUsdCost
} from "./crawlerNumberFormat";
import { getCrawlerScheduledIntervalLabel } from "./crawlerScheduledAggregate";

export type CrawlerTenantWebsiteProcessingAggregateResponse =
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateResponse"];
export type CrawlerTenantWebsiteProcessingAggregateItem =
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"];
export type CrawlerWebsiteProcessingSort = components["schemas"]["CrawlerWebsiteProcessingSort"];

// Backend caps at 200 per page; the Aktivitet UI exposes 10/25/50 so an
// operator with 10k websites can widen without overwhelming the column
// layout. 10 is the default — large enough to surface several failure
// clusters per page, small enough to render below the fold on a laptop.
export const CRAWLER_WEBSITE_PROCESSING_DEFAULTS = {
  days: 7,
  limit: 10,
  offset: 0,
  sort: "load_pressure" as const
} as const satisfies {
  days: number;
  limit: number;
  offset: number;
  sort: CrawlerWebsiteProcessingSort;
};

export const CRAWLER_WEBSITE_PROCESSING_PAGE_SIZES: readonly number[] = [10, 25, 50] as const;

export type CrawlerWebsiteProcessingPageSize =
  (typeof CRAWLER_WEBSITE_PROCESSING_PAGE_SIZES)[number];

export function isCrawlerWebsiteProcessingPageSize(
  value: number
): value is CrawlerWebsiteProcessingPageSize {
  return (CRAWLER_WEBSITE_PROCESSING_PAGE_SIZES as readonly number[]).includes(value);
}

// 7 / 14 / 30 days matches the backend's `days` Query bounds (1..30) and
// covers the operator's typical "did anything break this week / sprint /
// month" rhythm. 1 / 30 are not useful as chip values — too noisy / too
// coarse — so the chip set is a curated trio rather than a free integer.
export const CRAWLER_WEBSITE_PROCESSING_TIME_WINDOWS: readonly number[] = [7, 14, 30] as const;

export type CrawlerWebsiteProcessingTimeWindow =
  (typeof CRAWLER_WEBSITE_PROCESSING_TIME_WINDOWS)[number];

export function isCrawlerWebsiteProcessingTimeWindow(
  value: number
): value is CrawlerWebsiteProcessingTimeWindow {
  return (CRAWLER_WEBSITE_PROCESSING_TIME_WINDOWS as readonly number[]).includes(value);
}

export const CRAWLER_WEBSITE_PROCESSING_SORT_OPTIONS: readonly CrawlerWebsiteProcessingSort[] = [
  "load_pressure",
  "failures",
  "runs",
  "recent"
] as const;

export function getCrawlerWebsiteProcessingSortLabel(sort: CrawlerWebsiteProcessingSort): string {
  switch (sort) {
    case "load_pressure":
      return m.crawler_website_processing_sort_load_pressure();
    case "failures":
      return m.crawler_website_processing_sort_failures();
    case "runs":
      return m.crawler_website_processing_sort_runs();
    case "recent":
      return m.crawler_website_processing_sort_recent();
    default: {
      const exhaustive: never = sort;
      return exhaustive;
    }
  }
}

export function offsetFromCrawlerWebsiteProcessingPage(page: number, pageSize: number): number {
  if (pageSize <= 0) return 0;
  return Math.max(0, page - 1) * pageSize;
}

export function pageFromCrawlerWebsiteProcessingOffset(offset: number, pageSize: number): number {
  if (pageSize <= 0) return 1;
  return Math.max(1, Math.floor(Math.max(0, offset) / pageSize) + 1);
}

export function getCrawlerWebsiteProcessingWebsiteLabel(
  item: CrawlerTenantWebsiteProcessingAggregateItem
): string {
  const websiteName = item.website_name?.trim();
  if (websiteName) return websiteName;

  return m.crawler_website_processing_unknown_website({
    id: item.website_id.slice(0, 8)
  });
}

export function getCrawlerWebsiteProcessingTotalLabel(
  aggregate: CrawlerTenantWebsiteProcessingAggregateResponse
): string {
  return m.crawler_website_processing_total({
    shown: formatCrawlerCount(aggregate.items.length),
    total: formatCrawlerCount(aggregate.total),
    days: aggregate.days
  });
}

export function getCrawlerWebsiteProcessingFetchedLabel(
  item: CrawlerTenantWebsiteProcessingAggregateItem
): string {
  return m.crawler_website_processing_fetched({
    pages: formatCrawlerCount(item.pages_crawled),
    files: formatCrawlerCount(item.files_downloaded)
  });
}

export function getCrawlerWebsiteProcessingLoadPressureLabel(
  item: CrawlerTenantWebsiteProcessingAggregateItem
): string {
  return m.crawler_website_processing_load_pressure({
    interval:
      item.update_interval === null
        ? m.crawler_website_processing_unknown_interval()
        : getCrawlerScheduledIntervalLabel(item.update_interval),
    score: formatCrawlerDecimal(item.cost_pressure_score),
    retentionRate: formatCrawlerPercent(item.retention_rate)
  });
}

export function getCrawlerWebsiteProcessingRetainedLabel(
  item: CrawlerTenantWebsiteProcessingAggregateItem
): string {
  const retained = item.pages_hash_retained + item.files_hash_retained + item.pages_source_retained;
  return m.crawler_website_processing_retained({
    retained: formatCrawlerCount(retained),
    tooLarge: formatCrawlerCount(item.files_too_large_skipped)
  });
}

export function getCrawlerWebsiteProcessingFailureLabel(
  item: CrawlerTenantWebsiteProcessingAggregateItem
): string | null {
  const failedItems = item.pages_failed + item.files_failed;
  if (item.failed_runs === 0 && failedItems === 0) return null;

  return m.crawler_website_processing_failures({
    runs: formatCrawlerCount(item.failed_runs),
    items: formatCrawlerCount(failedItems)
  });
}

export function getCrawlerWebsiteProcessingEmbeddingUsageLabel(
  item: CrawlerTenantWebsiteProcessingAggregateItem
): string {
  if (item.embedding_input_tokens === null || item.embedding_input_tokens === undefined) {
    return m.crawler_website_processing_embedding_usage_unknown();
  }

  const tokens = formatCrawlerCount(item.embedding_input_tokens);
  if (item.embedding_input_tokens === 0) {
    return m.crawler_website_processing_embedding_usage_no_new_tokens();
  }
  if (!item.embedding_total_cost_usd) {
    return m.crawler_website_processing_embedding_usage_cost_missing({ tokens });
  }

  return m.crawler_website_processing_embedding_usage({
    tokens,
    cost: formatCrawlerUsdCost(item.embedding_total_cost_usd)
  });
}

export function getCrawlerWebsiteProcessingLatestRunEmbeddingUsageLabel(
  item: CrawlerTenantWebsiteProcessingAggregateItem
): string {
  if (
    item.latest_embedding_input_tokens === null ||
    item.latest_embedding_input_tokens === undefined
  ) {
    return m.crawler_website_processing_embedding_usage_unknown();
  }

  const tokens = formatCrawlerCount(item.latest_embedding_input_tokens);
  if (item.latest_embedding_input_tokens === 0) {
    return m.crawler_website_processing_embedding_usage_no_new_tokens();
  }
  if (!item.latest_embedding_total_cost_usd) {
    return m.crawler_website_processing_embedding_usage_cost_missing({ tokens });
  }

  return m.crawler_website_processing_embedding_usage({
    tokens,
    cost: formatCrawlerUsdCost(item.latest_embedding_total_cost_usd)
  });
}

export function getCrawlerWebsiteProcessingLatestRunModelLabel(
  item: CrawlerTenantWebsiteProcessingAggregateItem
): string {
  return (
    item.latest_embedding_model_name_snapshot?.trim() ||
    item.latest_embedding_model_litellm_name_snapshot?.trim() ||
    m.crawler_website_processing_embedding_model_unknown()
  );
}

export function getCrawlerWebsiteProcessingLatestRunProviderLabel(
  item: CrawlerTenantWebsiteProcessingAggregateItem
): string {
  return (
    item.latest_embedding_model_provider_snapshot?.trim() ||
    m.crawler_website_processing_embedding_model_unknown()
  );
}

export function getCrawlerWebsiteProcessingLatestRunUsageSourceLabel(
  item: CrawlerTenantWebsiteProcessingAggregateItem
): string {
  switch (item.latest_embedding_usage_source) {
    case "provider_reported":
      return m.crawler_website_processing_embedding_usage_source_provider_reported();
    case "missing":
      return m.crawler_website_processing_embedding_usage_source_missing();
    default:
      return m.crawler_website_processing_embedding_usage_source_legacy();
  }
}

/**
 * Token-efficiency drift threshold below which a website's retention rate is
 * flagged as wasteful. A retention rate of 0.5 means at least half of the
 * indexed content was re-fetched and re-embedded rather than retained, which
 * is the operator-visible signal that the hash gate or sitemap source-skip
 * either isn't trusted or is regressing. Kept as a constant rather than a
 * per-tenant setting so the operator vocabulary stays stable across tenants.
 */
export const CRAWLER_LOW_RETENTION_THRESHOLD = 0.5;

/**
 * Drift signal: the row's retention rate is below the operator-visible
 * waste threshold. Indexed work without retention is the load the
 * token-efficiency tranche is meant to surface; the pressure score
 * identifies busy recurring crawls, and this flag explains whether
 * that load comes from poor retention.
 *
 * Rows with no indexed work (indexed_content_count == 0) are not low
 * retention; they're idle. Returning false keeps the UI from flagging
 * cold websites as wasteful.
 */
export function isCrawlerWebsiteProcessingLowRetention(
  item: CrawlerTenantWebsiteProcessingAggregateItem,
  threshold: number = CRAWLER_LOW_RETENTION_THRESHOLD
): boolean {
  if (item.indexed_content_count <= 0) return false;
  return item.retention_rate < threshold;
}

/**
 * Drift signal: source-skip (sitemap lastmod) appears to have stopped
 * helping this website. A high indexed_content_count with zero
 * pages_source_retained over a multi-day window is the operator
 * signal that the sitemap is either lying about lastmod or the
 * source-skip feature isn't being applied for this website. Cheap
 * websites (low indexed_content_count) aren't flagged — the signal
 * is only meaningful when there's enough work to compare.
 */
export const CRAWLER_SOURCE_SKIP_DRIFT_MIN_INDEXED = 50;

export function isCrawlerWebsiteProcessingSourceSkipDrift(
  item: CrawlerTenantWebsiteProcessingAggregateItem,
  minIndexed: number = CRAWLER_SOURCE_SKIP_DRIFT_MIN_INDEXED
): boolean {
  if (item.indexed_content_count < minIndexed) {
    return false;
  }
  return item.pages_source_retained === 0;
}
