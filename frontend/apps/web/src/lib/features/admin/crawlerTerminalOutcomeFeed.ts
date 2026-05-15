import type { components } from "@intric/intric-js";
import {
  getCrawlRunResultLabels,
  positiveCrawlCount,
  type CrawlOutcomeLabelSource,
  type CrawlRunResultLabel
} from "$lib/features/knowledge/crawlOutcomePresentation";

export type CrawlerTerminalOutcomeFeedItem = components["schemas"]["CrawlerRecentFailureItem"];

export function outcomeFromTerminalFeedItem(
  item: CrawlerTerminalOutcomeFeedItem
): CrawlOutcomeLabelSource {
  return {
    code: item.outcome_code
  };
}

export function getCrawlerTerminalOutcomeResultLabels(
  item: CrawlerTerminalOutcomeFeedItem
): CrawlRunResultLabel[] {
  const pagesFetched = positiveCrawlCount(item.pages_crawled);
  const filesDownloaded = positiveCrawlCount(item.files_downloaded);
  const pagesHashRetained = positiveCrawlCount(item.pages_hash_retained);
  const filesHashRetained = positiveCrawlCount(item.files_hash_retained);
  const pagesFailed = positiveCrawlCount(item.pages_failed);
  const filesFailed = positiveCrawlCount(item.files_failed);

  return getCrawlRunResultLabels({
    outcome: outcomeFromTerminalFeedItem(item),
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

function indexedCount(total: number, hashRetained: number, failed: number): number {
  return Math.max(total - hashRetained - failed, 0);
}
