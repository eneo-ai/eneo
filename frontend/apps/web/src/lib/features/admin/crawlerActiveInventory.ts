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

export function canAbortCrawlerActiveInventoryItem(item: CrawlerActiveInventoryItem): boolean {
  return item.lifecycle_state === "queued";
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
    case "RUNNING_ABORT_NOT_IMPLEMENTED":
      return m.crawler_abort_conflict_running();
    case "CRAWL_NOT_ABORTABLE":
      return m.crawler_abort_conflict_not_abortable();
    default: {
      const exhaustive: never = conflict.error_code;
      return exhaustive;
    }
  }
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
  RUNNING_ABORT_NOT_IMPLEMENTED: true,
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
