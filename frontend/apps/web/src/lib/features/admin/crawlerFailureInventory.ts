import type { components } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";
import { formatCrawlerCount } from "./crawlerNumberFormat";

export type CrawlerTenantFailureInventoryResponse =
  components["schemas"]["CrawlerTenantFailureInventoryResponse"];
export type CrawlerTenantFailureInventoryItem =
  components["schemas"]["CrawlerTenantFailureInventoryItem"];

export const CRAWLER_FAILURE_INVENTORY_DEFAULTS = {
  limit: 5,
  offset: 0
} as const;

export function getCrawlerFailureInventoryWebsiteLabel(
  item: CrawlerTenantFailureInventoryItem
): string {
  const websiteName = item.website_name?.trim();
  if (websiteName) return websiteName;

  const websiteUrl = item.website_url.trim();
  if (websiteUrl) return websiteUrl;

  return m.crawler_failure_inventory_unknown_website({
    id: item.website_id.slice(0, 8)
  });
}

export function getCrawlerFailureInventoryTotalLabel(
  inventory: CrawlerTenantFailureInventoryResponse
): string {
  return m.crawler_failure_inventory_count({
    shown: formatCrawlerCount(inventory.items.length),
    total: formatCrawlerCount(inventory.total)
  });
}

export function getCrawlerFailureInventoryStateLabel(
  item: CrawlerTenantFailureInventoryItem
): string {
  switch (item.state) {
    case "BACKED_OFF":
      return m.crawler_failure_inventory_state_backed_off();
    case "AUTO_DISABLED":
      return m.crawler_failure_inventory_state_paused();
    default: {
      const exhaustive: never = item.state;
      return exhaustive;
    }
  }
}

export function getCrawlerFailureInventoryStateTooltip(
  item: CrawlerTenantFailureInventoryItem
): string {
  switch (item.state) {
    case "BACKED_OFF":
      return m.crawler_failure_inventory_state_backed_off_tooltip();
    case "AUTO_DISABLED":
      return m.crawler_failure_inventory_state_paused_tooltip();
    default: {
      const exhaustive: never = item.state;
      return exhaustive;
    }
  }
}

export function getCrawlerFailureInventoryFailureLabel(
  item: CrawlerTenantFailureInventoryItem
): string {
  return m.crawler_failure_inventory_failures({
    count: formatCrawlerCount(item.consecutive_failures)
  });
}

export function getCrawlerFailureInventoryNextStepLabel(
  item: CrawlerTenantFailureInventoryItem
): string {
  if (item.state === "AUTO_DISABLED") {
    return m.crawler_failure_inventory_next_step_review_settings();
  }

  if (item.next_retry_at) {
    return m.crawler_failure_inventory_next_step_retry_at({
      time: formatCrawlerFailureInventoryDateTime(item.next_retry_at)
    });
  }

  return m.crawler_failure_inventory_next_step_no_retry();
}

export function getCrawlerFailureInventoryLastCrawledLabel(
  item: CrawlerTenantFailureInventoryItem
): string {
  if (!item.last_crawled_at) {
    return m.crawler_failure_inventory_last_crawled_never();
  }

  return formatCrawlerFailureInventoryDateTime(item.last_crawled_at);
}

function formatCrawlerFailureInventoryDateTime(value: string): string {
  return new Date(value).toLocaleString(getLocale(), {
    dateStyle: "medium",
    timeStyle: "short"
  });
}
