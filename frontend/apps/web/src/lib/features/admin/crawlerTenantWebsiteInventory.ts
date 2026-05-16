/**
 * Tenant-wide website governance inventory.
 *
 * Backs the Webbplatser admin tab. Mirrors the shape of the active /
 * failure inventory modules: response/item type aliases pulled from the
 * generated openapi schema, defaults that match the backend Query
 * params, pure label helpers consumed by the table cells, and the
 * page↔offset math used by `Pagination.Root`.
 */
import type { components } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";

export type CrawlerTenantWebsiteInventoryResponse =
  components["schemas"]["CrawlerTenantWebsiteInventoryResponse"];
export type CrawlerTenantWebsiteInventoryItem =
  components["schemas"]["CrawlerTenantWebsiteInventoryItem"];
export type CrawlerTenantWebsiteInventorySort =
  components["schemas"]["CrawlerTenantWebsiteInventorySort"];
export type CrawlerFailureState = components["schemas"]["CrawlerFailureState"];

// 25 rows matches the active inventory page size so an admin paging
// through Drift → Webbplatser gets a consistent rhythm. Backend caps at
// 200; UI exposes 25 / 50 / 100 so very large tenants can widen.
export const CRAWLER_TENANT_WEBSITE_INVENTORY_DEFAULTS = {
  limit: 25,
  offset: 0,
  sort: "recent_crawl" as const
} as const satisfies {
  limit: number;
  offset: number;
  sort: CrawlerTenantWebsiteInventorySort;
};

export const CRAWLER_TENANT_WEBSITE_INVENTORY_PAGE_SIZES: readonly number[] = [
  25, 50, 100
] as const;

export type CrawlerTenantWebsiteInventoryPageSize =
  (typeof CRAWLER_TENANT_WEBSITE_INVENTORY_PAGE_SIZES)[number];

export function isCrawlerTenantWebsiteInventoryPageSize(
  value: number
): value is CrawlerTenantWebsiteInventoryPageSize {
  return (CRAWLER_TENANT_WEBSITE_INVENTORY_PAGE_SIZES as readonly number[]).includes(value);
}

export function offsetFromCrawlerTenantWebsiteInventoryPage(
  page: number,
  pageSize: number
): number {
  if (pageSize <= 0) return 0;
  return Math.max(0, page - 1) * pageSize;
}

export function pageFromCrawlerTenantWebsiteInventoryOffset(
  offset: number,
  pageSize: number
): number {
  if (pageSize <= 0) return 1;
  return Math.max(1, Math.floor(Math.max(0, offset) / pageSize) + 1);
}

/**
 * Human-readable label for the website cell. Prefers the operator-set
 * `name`; falls back to the URL when the name is empty so a row never
 * renders as a blank link. The hash-truncated id is the last-resort
 * fallback for rows where both name and URL are missing — but in
 * practice the schema makes `url` non-nullable, so the third branch is
 * defensive only.
 */
export function getCrawlerTenantWebsiteInventoryDisplayName(
  item: CrawlerTenantWebsiteInventoryItem
): string {
  const name = item.name?.trim();
  if (name) return name;
  const url = item.url?.trim();
  if (url) return url;
  return m.crawler_active_inventory_unknown_website({
    id: item.website_id.slice(0, 8)
  });
}

/**
 * Status badge label. Healthy is "Frisk"; the failure-state classifier
 * is shared with the Hälsa tab so an admin sees the same words.
 */
export function getCrawlerTenantWebsiteInventoryStatusLabel(
  item: CrawlerTenantWebsiteInventoryItem
): string {
  switch (item.failure_state) {
    case "AUTO_DISABLED":
      return m.crawler_failure_inventory_state_paused();
    case "BACKED_OFF":
      return m.crawler_failure_inventory_state_backed_off();
    case null:
      return m.crawler_tenant_website_inventory_state_healthy();
    default: {
      const exhaustive: never = item.failure_state;
      return exhaustive;
    }
  }
}

export function getCrawlerTenantWebsiteInventoryOwnerLabel(
  item: CrawlerTenantWebsiteInventoryItem
): string {
  const email = item.owner_email?.trim();
  return email && email.length > 0 ? email : m.crawler_active_inventory_started_by_unknown();
}

export function getCrawlerTenantWebsiteInventorySpaceLabel(
  item: CrawlerTenantWebsiteInventoryItem
): string {
  const space = item.space_name?.trim();
  const collection = item.collection_name?.trim();
  if (space && collection) {
    return `${space} › ${collection}`;
  }
  if (space) return space;
  if (collection) return collection;
  return m.crawler_active_inventory_source_unknown();
}

/**
 * Visibility decision for the detail Dialog's action buttons.
 *
 * Pulled out as a pure function so the 6 visibility quadrants
 * (failure_state ∈ {null, AUTO_DISABLED, BACKED_OFF} × active_job ∈
 * {null, present}) can be unit-tested without a DOM mount harness.
 * The Dialog component reads this once per render and conditionally
 * mounts each Button.
 *
 * `delete` is always visible because the operator should be able to
 * remove a registered website regardless of its current state — the
 * typed-URL confirmation guards against accidental clicks. `retry`
 * and `interval` are likewise always visible: an admin may want to
 * re-queue a healthy site or change the schedule of a paused one.
 */
export interface WebsiteDetailDialogActionVisibility {
  retry: boolean;
  interval: boolean;
  reset: boolean;
  abort: boolean;
  delete: boolean;
}

export function getWebsiteDetailDialogActionVisibility(args: {
  candidate: CrawlerTenantWebsiteInventoryItem | null;
  hasActiveJob: boolean;
}): WebsiteDetailDialogActionVisibility {
  if (args.candidate === null) {
    return {
      retry: false,
      interval: false,
      reset: false,
      abort: false,
      delete: false
    };
  }
  return {
    retry: true,
    interval: true,
    reset: args.candidate.failure_state !== null,
    abort: args.hasActiveJob,
    delete: true
  };
}
