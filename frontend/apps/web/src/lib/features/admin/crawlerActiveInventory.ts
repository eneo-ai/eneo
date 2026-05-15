import type { components } from "@intric/intric-js";
import {
  getCrawlRunResultLabels,
  positiveCrawlCount,
  type CrawlRunResultLabel
} from "$lib/features/knowledge/crawlOutcomePresentation";
import { m } from "$lib/paraglide/messages";

export type CrawlerActiveInventoryResponse =
  components["schemas"]["CrawlerActiveInventoryResponse"];
export type CrawlerActiveInventoryItem = components["schemas"]["CrawlerActiveInventoryItem"];

export const CRAWLER_ACTIVE_INVENTORY_DEFAULTS = {
  limit: 8,
  offset: 0
} as const;

export function getCrawlerActiveInventoryWebsiteLabel(item: CrawlerActiveInventoryItem): string {
  const websiteName = item.website_name?.trim();
  if (websiteName) return websiteName;

  if (item.website_id) {
    return m.crawler_active_inventory_unknown_website({
      id: item.website_id.slice(0, 8)
    });
  }

  return m.crawler_active_inventory_unknown_job({
    id: item.job_id.slice(0, 8)
  });
}

export function getCrawlerActiveInventoryStatusLabel(item: CrawlerActiveInventoryItem): string {
  switch (item.lifecycle_state) {
    case "queued":
      return m.crawler_active_inventory_status_queued();
    case "running_no_progress":
      return m.crawler_active_inventory_status_running_no_progress();
    case "running_with_progress":
      return m.crawler_active_inventory_status_running_with_progress();
    case "terminal":
      return m.crawler_active_inventory_status_terminal();
    default: {
      const exhaustive: never = item.lifecycle_state;
      return exhaustive;
    }
  }
}

export function getCrawlerActiveInventoryResultLabels(
  item: CrawlerActiveInventoryItem
): CrawlRunResultLabel[] {
  const pagesFetched = positiveCrawlCount(item.pages_crawled);
  const filesDownloaded = positiveCrawlCount(item.files_downloaded);
  const pagesHashRetained = positiveCrawlCount(item.pages_hash_retained);
  const filesHashRetained = positiveCrawlCount(item.files_hash_retained);
  const pagesFailed = positiveCrawlCount(item.pages_failed);
  const filesFailed = positiveCrawlCount(item.files_failed);

  return getCrawlRunResultLabels({
    pages_crawled: pagesFetched,
    files_downloaded: filesDownloaded,
    pages_hash_retained: pagesHashRetained,
    files_hash_retained: filesHashRetained,
    files_too_large_skipped: positiveCrawlCount(item.files_too_large_skipped),
    pages_source_retained: positiveCrawlCount(item.pages_source_retained),
    pages_failed: pagesFailed,
    files_failed: filesFailed
  });
}
