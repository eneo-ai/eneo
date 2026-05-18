import type { components } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";
import type { CrawlerTenantWebsiteInventoryItem } from "./crawlerTenantWebsiteInventory";
import { getCrawlerTenantWebsiteInventoryDisplayName } from "./crawlerTenantWebsiteInventory";
import type { CrawlerUpdateInterval } from "./crawlerUpdateInterval";

export type CrawlerBulkIntervalResponse = components["schemas"]["CrawlerBulkIntervalResponse"];

export type CrawlerBulkIntervalFailureCode = components["schemas"]["BulkIntervalRowFailureCode"];

/**
 * Server-side cap on the bulk endpoint. The endpoint rejects above
 * this size with 422 before touching the repo, so the client should
 * keep its own selection ≤ this value to avoid the round-trip on the
 * obvious-overflow case. Mirrors `BULK_INTERVAL_MAX_WEBSITE_IDS` in
 * `backend/src/intric/websites/domain/bulk_crawl_interval_change.py`.
 *
 * "Select all matching filter" needs a separate same-transaction
 * filter-and-audit contract before this client cap can be removed.
 */
export const CRAWLER_BULK_INTERVAL_MAX_WEBSITE_IDS = 100;

// Keep failed-row previews bounded so a valid 100-row batch cannot
// push the dialog actions below the fold.
export const CRAWLER_BULK_INTERVAL_FAILED_PREVIEW_LIMIT = 5;

export function getCrawlerBulkIntervalConfirmCopy(args: {
  selected_count: number;
  interval: CrawlerUpdateInterval;
}): string {
  return m.crawler_bulk_interval_confirm_body({
    count: String(args.selected_count),
    interval_label: getCrawlerBulkIntervalIntervalLabel(args.interval)
  });
}

function getCrawlerBulkIntervalIntervalLabel(value: CrawlerUpdateInterval): string {
  switch (value) {
    case "never":
      return m.crawler_scheduled_interval_never();
    case "daily":
      return m.crawler_scheduled_interval_daily();
    case "every_other_day":
      return m.crawler_scheduled_interval_every_other_day();
    case "weekly":
      return m.crawler_scheduled_interval_weekly();
    default: {
      const exhaustive: never = value;
      return exhaustive;
    }
  }
}

export function getCrawlerBulkIntervalSummaryLabel(response: CrawlerBulkIntervalResponse): string {
  return m.crawler_bulk_interval_summary({
    applied: String(response.applied.length),
    unchanged: String(response.unchanged.length),
    failed: String(response.failed.length)
  });
}

export function getCrawlerBulkIntervalFailureLabel(code: CrawlerBulkIntervalFailureCode): string {
  switch (code) {
    case "NOT_FOUND":
      return m.crawler_bulk_interval_failure_not_found();
    default: {
      const exhaustive: never = code;
      return exhaustive;
    }
  }
}

export function getCrawlerBulkIntervalFailedPreview(
  failed: CrawlerBulkIntervalResponse["failed"],
  limit: number = CRAWLER_BULK_INTERVAL_FAILED_PREVIEW_LIMIT
): {
  rendered: { website_id: string; code: CrawlerBulkIntervalFailureCode }[];
  remaining: number;
} | null {
  if (failed.length === 0) return null;
  if (failed.length <= limit) {
    return { rendered: failed.slice(), remaining: 0 };
  }
  return {
    rendered: failed.slice(0, limit),
    remaining: failed.length - limit
  };
}

export function canSubmitCrawlerBulkIntervalSelection(args: {
  selected_count: number;
  interval: CrawlerUpdateInterval | null;
}): boolean {
  if (args.interval === null) return false;
  if (args.selected_count < 1) return false;
  if (args.selected_count > CRAWLER_BULK_INTERVAL_MAX_WEBSITE_IDS) return false;
  return true;
}

export function getCrawlerBulkIntervalSelectedDisplayName(args: {
  website_id: string;
  visible_items: CrawlerTenantWebsiteInventoryItem[];
}): string {
  const found = args.visible_items.find((item) => item.website_id === args.website_id);
  if (found) return getCrawlerTenantWebsiteInventoryDisplayName(found);
  return args.website_id;
}
