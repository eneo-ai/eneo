import type { TableSortComparator, TableSortState } from "@astryxdesign/core/Table";
import { formatWebsiteName, type Collection, type Website } from "./knowledge";

/**
 * Column comparators for the knowledge tables, fed to Astryx Table's
 * `useTableSortableState`. They compare values, never labels: derived names
 * through the provider-bound collator (`useCollator`), dates as timestamps,
 * states by severity. Astryx reverses them for descending order.
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

/** Problems first: failed, then warnings, running, queued, never crawled, done. */
export function websiteStatusRank(website: Website): number {
  const crawl = website.latest_crawl;
  if (!crawl) return 4;
  switch (crawl.status) {
    case "complete":
      return (crawl.pages_failed ?? 0) > 0 || (crawl.files_failed ?? 0) > 0 ? 1 : 5;
    case "in progress":
      return 2;
    case "queued":
      return 3;
    default:
      return 0;
  }
}

/** When the latest crawl finished (or started, while it runs). */
export function websiteSyncedAt(website: Website): string | null {
  return website.latest_crawl?.finished_at ?? website.latest_crawl?.created_at ?? null;
}

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
    status: (a, b) => websiteStatusRank(a) - websiteStatusRank(b),
    synced: (a, b) => time(websiteSyncedAt(a)) - time(websiteSyncedAt(b)),
    interval: (a, b) => INTERVAL_ORDER[a.update_interval] - INTERVAL_ORDER[b.update_interval]
  };
}
