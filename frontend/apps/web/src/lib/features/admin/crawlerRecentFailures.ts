import type { components } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";
import {
  getCrawlOutcomeLabel,
  type CrawlRunResultLabel
} from "$lib/features/knowledge/crawlOutcomePresentation";
import {
  getCrawlerTerminalOutcomeResultLabels,
  outcomeFromTerminalFeedItem
} from "$lib/features/admin/crawlerTerminalOutcomeFeed";

export type CrawlerRecentFailuresResponse = components["schemas"]["CrawlerRecentFailuresResponse"];
export type CrawlerRecentFailureItem = components["schemas"]["CrawlerRecentFailureItem"];
// 25 rows fits comfortably in a 1080p viewport without scrolling and
// matches the active inventory page size, so an admin paging through
// the operations and health tabs gets consistent rhythm. Operators
// drilling into 7-day failure history can `prev`/`next` past page 1
// when `total` exceeds the limit.
export const CRAWLER_RECENT_FAILURES_DEFAULTS = {
  days: 7,
  limit: 25,
  offset: 0
} as const;

export const CRAWLER_RECENT_FAILURES_PAGE_SIZE = CRAWLER_RECENT_FAILURES_DEFAULTS.limit;

export function offsetFromCrawlerRecentFailuresPage(
  page: number,
  pageSize: number = CRAWLER_RECENT_FAILURES_PAGE_SIZE
): number {
  if (pageSize <= 0) return 0;
  return Math.max(0, page - 1) * pageSize;
}

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
  return getCrawlOutcomeLabel(outcomeFromTerminalFeedItem(item), m.crawl_outcome_unknown_error());
}

export function getCrawlerRecentFailureResultLabels(
  item: CrawlerRecentFailureItem
): CrawlRunResultLabel[] {
  return getCrawlerTerminalOutcomeResultLabels(item);
}
