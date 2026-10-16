import type { TableSortComparator, TableSortState } from "@astryxdesign/core/Table";
import { formatWebsiteName, type Collection, type CrawlRun, type Website } from "./knowledge";
import { crawlRunStatus, statusRank, websiteStatus, websiteSyncedAt } from "./website-status";

/**
 * Column comparators for the knowledge tables, fed to Astryx Table's
 * `useTableSortableState`. They compare values, never labels: derived names
 * through the provider-bound collator (`useCollator`), dates as timestamps,
 * states by the severity of the status the table shows (`statusRank`).
 * Astryx reverses them for descending order.
 */

type Compare = (a: string, b: string) => number;

function time(value: string | null | undefined): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

export type CollectionSortKey = "name" | "files" | "updated";

export const COLLECTION_DEFAULT_SORT: TableSortState<CollectionSortKey> = [
  { sortKey: "name", direction: "ascending" }
];

/** `name` sorts with Astryx's default (collator over the field itself). */
export const COLLECTION_COMPARATORS: Partial<
  Record<CollectionSortKey, TableSortComparator<Collection>>
> = {
  files: (a, b) => a.metadata.num_info_blobs - b.metadata.num_info_blobs,
  updated: (a, b) => time(a.updated_at ?? a.created_at) - time(b.updated_at ?? b.created_at)
};

export type WebsiteSortKey = "name" | "status" | "synced" | "interval";

export const WEBSITE_DEFAULT_SORT: TableSortState<WebsiteSortKey> = [
  { sortKey: "name", direction: "ascending" }
];

const INTERVAL_ORDER: Record<Website["update_interval"], number> = {
  daily: 0,
  every_other_day: 1,
  weekly: 2,
  never: 3
};

export function websiteComparators(
  compare: Compare
): Record<WebsiteSortKey, TableSortComparator<Website>> {
  return {
    name: (a, b) => compare(formatWebsiteName(a), formatWebsiteName(b)),
    status: (a, b) => statusRank(websiteStatus(a)) - statusRank(websiteStatus(b)),
    synced: (a, b) => time(websiteSyncedAt(a)) - time(websiteSyncedAt(b)),
    interval: (a, b) => INTERVAL_ORDER[a.update_interval] - INTERVAL_ORDER[b.update_interval]
  };
}

export type CrawlRunSortKey = "started" | "status" | "results" | "duration";

/** Newest crawl first. */
export const CRAWL_RUN_DEFAULT_SORT: TableSortState<CrawlRunSortKey> = [
  { sortKey: "started", direction: "descending" }
];

/** Pages and files the crawl fetched. */
export function crawlRunResultCount(crawl: CrawlRun): number {
  return (crawl.pages_crawled ?? 0) + (crawl.files_downloaded ?? 0);
}

/** How long a finished crawl took; 0 while it runs. */
function crawlRunDurationMs(crawl: CrawlRun): number {
  const started = time(crawl.created_at);
  const finished = time(crawl.finished_at);
  return started && finished ? Math.max(0, finished - started) : 0;
}

export const CRAWL_RUN_COMPARATORS: Record<CrawlRunSortKey, TableSortComparator<CrawlRun>> = {
  started: (a, b) => time(a.created_at) - time(b.created_at),
  status: (a, b) => statusRank(crawlRunStatus(a)) - statusRank(crawlRunStatus(b)),
  results: (a, b) => crawlRunResultCount(a) - crawlRunResultCount(b),
  duration: (a, b) => crawlRunDurationMs(a) - crawlRunDurationMs(b)
};
