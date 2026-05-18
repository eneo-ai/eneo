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

export const CRAWLER_WEBSITE_PROCESSING_DEFAULTS = {
  days: 7,
  limit: 5,
  offset: 0
} as const;

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
  item: CrawlerTenantWebsiteProcessingAggregateItem
): boolean {
  if (item.indexed_content_count <= 0) return false;
  return item.retention_rate < CRAWLER_LOW_RETENTION_THRESHOLD;
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
  item: CrawlerTenantWebsiteProcessingAggregateItem
): boolean {
  if (item.indexed_content_count < CRAWLER_SOURCE_SKIP_DRIFT_MIN_INDEXED) {
    return false;
  }
  return item.pages_source_retained === 0;
}
