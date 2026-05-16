import { IntricError, type components } from "@intric/intric-js";
import {
  getCrawlRunResultLabels,
  positiveCrawlCount,
  type CrawlRunResultLabel
} from "$lib/features/knowledge/crawlOutcomePresentation";
import { m } from "$lib/paraglide/messages";

export type CrawlerActiveInventoryResponse =
  components["schemas"]["CrawlerActiveInventoryResponse"];
export type CrawlerActiveInventoryItem = components["schemas"]["CrawlerActiveInventoryItem"];
type CrawlerAbortConflictCode = components["schemas"]["CrawlAbortConflictCode"];
type CrawlerAbortConflictResponse = components["schemas"]["CrawlerAbortConflictResponse"];

export const CRAWLER_ACTIVE_INVENTORY_DEFAULTS = {
  // 25 fits comfortably on a 1080p screen without forcing a second
  // scroll just to see the abort button. The backend caps `limit` at
  // 200; the UI also exposes 50/100 via CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES
  // so operators with hundreds of in-flight crawls don't have to paginate
  // through 25-row pages to find the one they need to cancel.
  limit: 25,
  offset: 0
} as const;

export const CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES: readonly number[] = [25, 50, 100] as const;

export type CrawlerActiveInventoryPageSize = (typeof CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES)[number];

export function isCrawlerActiveInventoryPageSize(
  value: number
): value is CrawlerActiveInventoryPageSize {
  return (CRAWLER_ACTIVE_INVENTORY_PAGE_SIZES as readonly number[]).includes(value);
}

export function pageFromCrawlerActiveInventoryOffset(offset: number, pageSize: number): number {
  if (pageSize <= 0) return 1;
  return Math.max(1, Math.floor(Math.max(0, offset) / pageSize) + 1);
}

export function offsetFromCrawlerActiveInventoryPage(page: number, pageSize: number): number {
  if (pageSize <= 0) return 0;
  return Math.max(0, page - 1) * pageSize;
}

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

export function canAbortCrawlerActiveInventoryItem(item: CrawlerActiveInventoryItem): boolean {
  return item.is_abortable;
}

export function getCrawlerAbortConflictMessage(error: unknown): string | null {
  if (!(error instanceof IntricError) || error.status !== 409) {
    return null;
  }

  const conflict = readCrawlerAbortConflict(error.response);
  if (conflict === null) {
    return null;
  }

  switch (conflict.error_code) {
    case "CRAWL_NOT_ABORTABLE":
      return m.crawler_abort_conflict_not_abortable();
    default: {
      const exhaustive: never = conflict.error_code;
      return exhaustive;
    }
  }
}

export function isCrawlerActiveInventoryItemRunning(item: CrawlerActiveInventoryItem): boolean {
  return (
    item.lifecycle_state === "running_no_progress" ||
    item.lifecycle_state === "running_with_progress"
  );
}

export type CrawlerActiveInventoryLifecycleFilter =
  | "all"
  | "queued"
  | "running_with_progress"
  | "running_no_progress";

export const CRAWLER_ACTIVE_INVENTORY_LIFECYCLE_FILTER_OPTIONS: readonly CrawlerActiveInventoryLifecycleFilter[] =
  ["all", "queued", "running_with_progress", "running_no_progress"] as const;

export function getCrawlerActiveInventoryLifecycleFilterLabel(
  value: CrawlerActiveInventoryLifecycleFilter
): string {
  switch (value) {
    case "all":
      return m.crawler_active_inventory_filter_all();
    case "queued":
      return m.crawler_active_inventory_status_queued();
    case "running_with_progress":
      return m.crawler_active_inventory_status_running_with_progress();
    case "running_no_progress":
      return m.crawler_active_inventory_status_running_no_progress();
    default: {
      const exhaustive: never = value;
      return exhaustive;
    }
  }
}

export function getCrawlerActiveInventorySourceLabel(
  item: CrawlerActiveInventoryItem
): string | null {
  const space = item.space_name?.trim();
  const collection = item.collection_name?.trim();
  if (space && collection) {
    return `${space} › ${collection}`;
  }
  if (space) {
    return space;
  }
  if (collection) {
    return collection;
  }
  return null;
}

export function getCrawlerActiveInventoryStartedByLabel(
  item: CrawlerActiveInventoryItem
): string | null {
  const email = item.user_started_by_email?.trim();
  return email && email.length > 0 ? email : null;
}

function readCrawlerAbortConflict(value: unknown): CrawlerAbortConflictResponse | null {
  const response = readObject(value);
  if (response === null) return null;

  return readConflictResponse(response);
}

function readConflictResponse(
  value: Record<string, unknown> | null
): CrawlerAbortConflictResponse | null {
  if (value === null) return null;
  const errorCode = value.error_code;
  const detail = value.detail;
  if (!isCrawlerAbortConflictCode(errorCode) || typeof detail !== "string") {
    return null;
  }
  return { error_code: errorCode, detail };
}

function readObject(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

const crawlAbortConflictCodes = {
  CRAWL_NOT_ABORTABLE: true
} satisfies Record<CrawlerAbortConflictCode, true>;

function isCrawlerAbortConflictCode(value: unknown): value is CrawlerAbortConflictCode {
  return typeof value === "string" && value in crawlAbortConflictCodes;
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
