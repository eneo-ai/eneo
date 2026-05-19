import { expect, test } from "vitest";
import type { Intric } from "@intric/intric-js";
import type { CrawlerActiveInventoryItem } from "$lib/features/admin/crawlerActiveInventory";
import type { CrawlerTenantFailureInventoryItem } from "$lib/features/admin/crawlerFailureInventory";
import type { CrawlerTenantWebsiteInventoryItem } from "$lib/features/admin/crawlerTenantWebsiteInventory";
import {
  createCrawlerDialogState,
  getCrawlerIntervalChangeInvalidationKeys
} from "./crawlerAdminPageState.svelte";

function createDialogStateForTest() {
  return createCrawlerDialogState(
    {} as Intric,
    { set: () => undefined },
    {
      visibleActiveInventory: async () => undefined,
      visibleFailureClusters: async () => undefined,
      visibleTenantWebsiteInventory: async () => undefined
    }
  );
}

test("inventory interval changes invalidate the visible website inventory query", () => {
  expect(getCrawlerIntervalChangeInvalidationKeys("tenant_inventory")).toContain(
    "admin:crawler-tenant-website-inventory"
  );
});

test("non-inventory interval changes avoid unnecessary inventory refreshes", () => {
  expect(getCrawlerIntervalChangeInvalidationKeys("failure_inventory")).not.toContain(
    "admin:crawler-tenant-website-inventory"
  );
  expect(getCrawlerIntervalChangeInvalidationKeys("active_inventory")).not.toContain(
    "admin:crawler-tenant-website-inventory"
  );
});

test("interval dialog source flows from each public opener", () => {
  const dialogs = createDialogStateForTest();
  dialogs.interval.openForInventoryItem({
    website_id: "website-inventory",
    name: "Inventory",
    url: "https://example.com",
    update_interval: "weekly"
  } as CrawlerTenantWebsiteInventoryItem);
  expect(dialogs.interval.candidate?.source).toBe("tenant_inventory");

  dialogs.interval.openForFailureItem({
    website_id: "website-failure",
    website_name: "Failure",
    website_url: "https://failure.example.com",
    update_interval: "daily"
  } as CrawlerTenantFailureInventoryItem);
  expect(dialogs.interval.candidate?.source).toBe("failure_inventory");

  dialogs.interval.openForActiveItem({
    website_id: "website-active",
    website_name: "Active",
    update_interval: "never"
  } as CrawlerActiveInventoryItem);
  expect(dialogs.interval.candidate?.source).toBe("active_inventory");
});
