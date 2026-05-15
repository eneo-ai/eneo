import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import type {
  CrawlerTenantFailureInventoryItem,
  CrawlerTenantFailureInventoryResponse
} from "./crawlerFailureInventory";
import {
  getCrawlerFailureInventoryFailureLabel,
  getCrawlerFailureInventoryLastCrawledLabel,
  getCrawlerFailureInventoryNextStepLabel,
  getCrawlerFailureInventoryStateLabel,
  getCrawlerFailureInventoryStateTooltip,
  getCrawlerFailureInventoryTotalLabel,
  getCrawlerFailureInventoryWebsiteLabel
} from "./crawlerFailureInventory";

overwriteGetLocale(() => "en");

const backedOffItem: CrawlerTenantFailureInventoryItem = {
  website_id: "12345678-1234-4234-8234-123456789abc",
  website_url: "https://example.com",
  website_name: "Example municipality",
  state: "BACKED_OFF",
  update_interval: "daily",
  consecutive_failures: 3,
  next_retry_at: "2026-05-15T10:30:00Z",
  last_crawled_at: "2026-05-14T08:15:00Z",
  updated_at: "2026-05-15T09:00:00Z"
};

const pausedItem: CrawlerTenantFailureInventoryItem = {
  ...backedOffItem,
  website_id: "87654321-1234-4234-8234-123456789abc",
  website_url: "https://paused.example.com",
  website_name: null,
  state: "AUTO_DISABLED",
  update_interval: "never",
  consecutive_failures: 10,
  next_retry_at: null,
  last_crawled_at: null
};

test("failure inventory labels explain current crawler state", () => {
  const inventory: CrawlerTenantFailureInventoryResponse = {
    items: [backedOffItem],
    total: 12,
    limit: 5,
    offset: 0
  };

  expect(getCrawlerFailureInventoryTotalLabel(inventory)).toBe("1 of 12 websites need attention");
  expect(getCrawlerFailureInventoryWebsiteLabel(backedOffItem)).toBe("Example municipality");
  expect(getCrawlerFailureInventoryStateLabel(backedOffItem)).toBe("Retry scheduled");
  expect(getCrawlerFailureInventoryStateTooltip(backedOffItem)).toBe(
    "The crawler failed recently and is waiting until the next retry window."
  );
  expect(getCrawlerFailureInventoryFailureLabel(backedOffItem)).toBe("3 consecutive failures");
  expect(getCrawlerFailureInventoryNextStepLabel(backedOffItem)).toContain("Retries");
  expect(getCrawlerFailureInventoryLastCrawledLabel(backedOffItem)).toContain("2026");
});

test("failure inventory labels avoid overclaiming paused crawler origin", () => {
  expect(getCrawlerFailureInventoryWebsiteLabel(pausedItem)).toBe("https://paused.example.com");
  expect(getCrawlerFailureInventoryStateLabel(pausedItem)).toBe("Paused after failures");
  expect(getCrawlerFailureInventoryStateTooltip(pausedItem)).toBe(
    "The schedule is manual-only after repeated failures. Review recent failures before enabling a recurring interval again."
  );
  expect(getCrawlerFailureInventoryFailureLabel(pausedItem)).toBe("10 consecutive failures");
  expect(getCrawlerFailureInventoryNextStepLabel(pausedItem)).toBe(
    "Review errors before scheduling again"
  );
  expect(getCrawlerFailureInventoryLastCrawledLabel(pausedItem)).toBe("Never");
});
