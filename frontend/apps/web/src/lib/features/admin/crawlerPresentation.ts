/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
 * See the LICENSE file at the repository root for the full license text.
 */

import { getLocale } from "$lib/paraglide/runtime";
import type { CrawlerActiveInventoryItem } from "./crawlerActiveInventory";
import type { CrawlerTenantFailureInventoryItem } from "./crawlerFailureInventory";
import type { CrawlRunResultLabel } from "$lib/features/knowledge/crawlOutcomePresentation";

export function formatCrawlerDateTime(value: string): string {
  return new Date(value).toLocaleString(getLocale(), {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

export function crawlerResultBadgeClass(color: CrawlRunResultLabel["color"]): string | undefined {
  switch (color) {
    case "orange":
      return "border-caution/40 bg-caution/8 text-caution";
    case "green":
      return "border-positive-default/40 bg-positive-dimmer text-positive-stronger";
    case "moss":
      return "border-success/40 bg-secondary text-success";
    case "blue":
      return "border-accent-default/35 text-accent-default";
    default:
      return undefined;
  }
}

export function crawlerActiveStatusBadgeClass(
  lifecycleState: CrawlerActiveInventoryItem["lifecycle_state"]
): string {
  switch (lifecycleState) {
    case "running_with_progress":
      return "border-positive-default/40 bg-positive-dimmer text-positive-stronger";
    case "running_no_progress":
      return "border-caution/40 bg-caution/8 text-caution";
    case "terminal":
      return "border-border text-muted-foreground";
    case "queued":
      return "border-accent-default/35 text-accent-default";
    default: {
      const exhaustive: never = lifecycleState;
      return exhaustive;
    }
  }
}

export function crawlerFailureStateBadgeClass(
  state: CrawlerTenantFailureInventoryItem["state"]
): string {
  switch (state) {
    case "BACKED_OFF":
      return "border-caution/40 bg-caution/8 text-caution";
    case "AUTO_DISABLED":
      return "border-destructive/35 bg-destructive/8 text-destructive";
    default: {
      const exhaustive: never = state;
      return exhaustive;
    }
  }
}
