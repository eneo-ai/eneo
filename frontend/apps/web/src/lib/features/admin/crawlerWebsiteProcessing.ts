import type { components } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";
import { formatCrawlerCount } from "./crawlerNumberFormat";

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
