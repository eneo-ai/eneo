import type { components } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";
import {
  getCrawlOutcomeLabel,
  getCrawlRunResultLabels,
  positiveCrawlCount,
  type CrawlOutcomeLabelSource,
  type CrawlRunResultLabel
} from "$lib/features/knowledge/crawlOutcomePresentation";

export type CrawlerRecentFailuresResponse = components["schemas"]["CrawlerRecentFailuresResponse"];
export type CrawlerRecentFailureItem = components["schemas"]["CrawlerRecentFailureItem"];
export const CRAWLER_RECENT_FAILURES_DEFAULTS = {
  days: 7,
  limit: 5,
  offset: 0
} as const;

export function getCrawlerRecentFailureWebsiteLabel(item: CrawlerRecentFailureItem): string {
  const websiteName = item.website_name?.trim();
  if (websiteName) {
    return websiteName;
  }

  return m.crawler_recent_failure_unknown_website({
    id: item.website_id.slice(0, 8)
  });
}

export function getCrawlerRecentFailureOutcomeLabel(item: CrawlerRecentFailureItem): string {
  return getCrawlOutcomeLabel(outcomeFromFailure(item), m.crawl_outcome_unknown_error());
}

export function getCrawlerRecentFailureResultLabels(
  item: CrawlerRecentFailureItem
): CrawlRunResultLabel[] {
  const pagesFetched = positiveCrawlCount(item.pages_crawled);
  const filesDownloaded = positiveCrawlCount(item.files_downloaded);
  const pagesHashRetained = positiveCrawlCount(item.pages_hash_retained);
  const filesHashRetained = positiveCrawlCount(item.files_hash_retained);
  const pagesFailed = positiveCrawlCount(item.pages_failed);
  const filesFailed = positiveCrawlCount(item.files_failed);

  return getCrawlRunResultLabels({
    outcome: outcomeFromFailure(item),
    failure_summary: item.failure_summary,
    processing_summary: {
      pages_fetched: pagesFetched,
      files_downloaded: filesDownloaded,
      pages_indexed: indexedCount(pagesFetched, pagesHashRetained, pagesFailed),
      files_indexed: indexedCount(filesDownloaded, filesHashRetained, filesFailed),
      pages_hash_retained: pagesHashRetained,
      files_hash_retained: filesHashRetained,
      files_too_large_skipped: positiveCrawlCount(item.files_too_large_skipped),
      pages_source_retained: positiveCrawlCount(item.pages_source_retained),
      pages_failed: pagesFailed,
      files_failed: filesFailed
    }
  });
}

function outcomeFromFailure(item: CrawlerRecentFailureItem): CrawlOutcomeLabelSource {
  return {
    code: item.outcome_code
  };
}

function indexedCount(total: number, hashRetained: number, failed: number): number {
  return Math.max(total - hashRetained - failed, 0);
}
