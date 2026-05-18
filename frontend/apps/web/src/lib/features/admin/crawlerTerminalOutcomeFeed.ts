import type { components } from "@intric/intric-js";
import {
  getCrawlRunResultLabels,
  positiveCrawlCount,
  type CrawlOutcomeLabelSource,
  type CrawlRunResultLabel
} from "$lib/features/knowledge/crawlOutcomePresentation";
import { formatCrawlerCount, formatCrawlerUsdCost } from "./crawlerNumberFormat";
import { m } from "$lib/paraglide/messages";

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

  const labels = getCrawlRunResultLabels({
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
  const embeddingUsageLabel = terminalEmbeddingUsageLabel(item);
  if (embeddingUsageLabel) {
    labels.push({
      color: "blue",
      label: embeddingUsageLabel
    });
  }
  return labels;
}

function indexedCount(total: number, hashRetained: number, failed: number): number {
  return Math.max(total - hashRetained - failed, 0);
}

function terminalEmbeddingUsageLabel(item: CrawlerTerminalOutcomeFeedItem): string | null {
  if (item.embedding_input_tokens === null || item.embedding_input_tokens === undefined) {
    return null;
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
