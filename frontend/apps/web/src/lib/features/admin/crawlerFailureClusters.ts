import type { components } from "@intric/intric-js";
import { getCrawlOutcomeLabel } from "$lib/features/knowledge/crawlOutcomePresentation";
import { m } from "$lib/paraglide/messages";
import { formatCrawlerDateTime } from "./crawlerPresentation";
import { formatCrawlerCount } from "./crawlerNumberFormat";

export type CrawlerFailureClustersResponse =
  components["schemas"]["CrawlerFailureClustersResponse"];
export type CrawlerFailureClusterItem = components["schemas"]["CrawlerFailureClusterItem"];

export const CRAWLER_FAILURE_CLUSTERS_DEFAULTS = {
  days: 7,
  limit: 10,
  offset: 0
} as const;

export const CRAWLER_FAILURE_CLUSTERS_PAGE_SIZE = CRAWLER_FAILURE_CLUSTERS_DEFAULTS.limit;

export function offsetFromCrawlerFailureClustersPage(
  page: number,
  pageSize: number = CRAWLER_FAILURE_CLUSTERS_PAGE_SIZE
): number {
  if (pageSize <= 0) return 0;
  return Math.max(0, page - 1) * pageSize;
}

export function getCrawlerFailureClusterWebsiteLabel(item: CrawlerFailureClusterItem): string {
  const websiteName = item.website_name?.trim();
  if (websiteName) return websiteName;

  const websiteUrl = item.website_url.trim();
  if (websiteUrl) return websiteUrl;

  return m.crawler_failure_cluster_unknown_website({
    id: item.website_id.slice(0, 8)
  });
}

export function getCrawlerFailureClusterOutcomeLabel(item: CrawlerFailureClusterItem): string {
  return getCrawlOutcomeLabel({ code: item.outcome_code }, m.crawl_outcome_unknown_error());
}

export function getCrawlerFailureClusterAttributionLabel(item: CrawlerFailureClusterItem): string {
  const space = item.space_name?.trim();
  const owner = item.owner_email?.trim();
  if (space && owner) {
    return m.crawler_failure_cluster_attribution_space_owner({ space, owner });
  }
  if (space) return space;
  if (owner) return owner;
  return m.crawler_failure_cluster_attribution_missing();
}

export function getCrawlerFailureClusterOccurrenceLabel(item: CrawlerFailureClusterItem): string {
  const occurrences = formatCrawlerCount(item.occurrences);
  if (item.watchdog_occurrences > 0) {
    return m.crawler_failure_cluster_occurrences_with_watchdog({
      occurrences,
      watchdog: formatCrawlerCount(item.watchdog_occurrences)
    });
  }
  return m.crawler_failure_cluster_occurrences({ occurrences });
}

export function getCrawlerFailureClusterWorkLabel(item: CrawlerFailureClusterItem): string {
  if (
    item.pages_crawled === 0 &&
    item.files_downloaded === 0 &&
    item.pages_failed + item.files_failed === 0
  ) {
    return m.crawler_failure_cluster_work_zero();
  }

  return m.crawler_failure_cluster_work({
    pages: formatCrawlerCount(item.pages_crawled),
    files: formatCrawlerCount(item.files_downloaded),
    failed: formatCrawlerCount(item.pages_failed + item.files_failed)
  });
}

export function getCrawlerFailureClusterLatestLabel(item: CrawlerFailureClusterItem): string {
  return formatCrawlerDateTime(item.latest_failed_at);
}
