import { expect, test, vi } from "vitest";
// SDK plumbing test: import the endpoint factory directly so we can wire
// it to a stub fetch and assert the wire contract (path, method, params)
// — `@intric/intric-js`'s public surface only exposes `createIntric`,
// so reaching the factory through its source file is the smallest
// arrangement for one boundary test.
import { initCrawlerAdmin } from "../../../../../../packages/intric-js/src/endpoints/crawler-admin.js";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import type { CrawlerTenantWebsiteInventoryItem } from "./crawlerTenantWebsiteInventory";
import {
  CRAWLER_TENANT_WEBSITE_INVENTORY_PAGE_SIZES,
  getCrawlerTenantWebsiteInventoryCrawlerStateParam,
  getCrawlerTenantWebsiteInventoryDisplayName,
  getCrawlerTenantWebsiteInventoryOwnerLabel,
  getCrawlerTenantWebsiteInventorySpaceLabel,
  getCrawlerTenantWebsiteInventoryStatusLabel,
  getWebsiteDetailDialogActionVisibility,
  isCrawlerTenantWebsiteInventoryPageSize,
  offsetFromCrawlerTenantWebsiteInventoryPage,
  pageFromCrawlerTenantWebsiteInventoryOffset
} from "./crawlerTenantWebsiteInventory";

overwriteGetLocale(() => "en");

const baseItem: CrawlerTenantWebsiteInventoryItem = {
  website_id: "12345678-1234-4234-8234-123456789abc",
  url: "https://example.com/news",
  name: "Example News",
  created_at: "2026-04-01T08:00:00.000Z",
  update_interval: "daily",
  crawl_type: "crawl",
  download_files: true,
  requires_http_auth: false,
  http_auth_username: null,
  failure_state: null,
  consecutive_failures: 0,
  next_retry_at: null,
  last_crawled_at: "2026-05-15T12:00:00.000Z",
  size: 1_048_576,
  owner_user_id: "11111111-1111-4111-8111-111111111111",
  owner_email: "operator@example.com",
  space_id: "22222222-2222-4222-8222-222222222222",
  space_name: "Org space",
  collection_id: "33333333-3333-4333-8333-333333333333",
  collection_name: "News collection"
};

test("display name prefers operator-set name, falls back to URL, then to id", () => {
  expect(getCrawlerTenantWebsiteInventoryDisplayName(baseItem)).toBe("Example News");
  expect(getCrawlerTenantWebsiteInventoryDisplayName({ ...baseItem, name: null })).toBe(
    "https://example.com/news"
  );
  // Defensive third branch: schema says url is non-null but the cell
  // helper must not return `undefined` if a malformed payload arrives.
  expect(
    getCrawlerTenantWebsiteInventoryDisplayName({
      ...baseItem,
      name: null,
      url: ""
    })
  ).toMatch(/12345678/);
});

test("status label routes the three failure_state values to the right copy", () => {
  expect(getCrawlerTenantWebsiteInventoryStatusLabel({ ...baseItem, failure_state: null })).toBe(
    "Healthy"
  );
  expect(
    getCrawlerTenantWebsiteInventoryStatusLabel({
      ...baseItem,
      failure_state: "AUTO_DISABLED"
    })
  ).toBe("Paused after failures");
  expect(
    getCrawlerTenantWebsiteInventoryStatusLabel({
      ...baseItem,
      failure_state: "BACKED_OFF"
    })
  ).toBe("Retry scheduled");
});

test("owner label falls back to unknown when email is absent or blank", () => {
  expect(getCrawlerTenantWebsiteInventoryOwnerLabel(baseItem)).toBe("operator@example.com");
  expect(getCrawlerTenantWebsiteInventoryOwnerLabel({ ...baseItem, owner_email: null })).toBe(
    "Unknown user"
  );
  expect(getCrawlerTenantWebsiteInventoryOwnerLabel({ ...baseItem, owner_email: "   " })).toBe(
    "Unknown user"
  );
});

test("space label composes space › collection when both are present", () => {
  expect(getCrawlerTenantWebsiteInventorySpaceLabel(baseItem)).toBe("Org space › News collection");
  expect(
    getCrawlerTenantWebsiteInventorySpaceLabel({
      ...baseItem,
      collection_name: null
    })
  ).toBe("Org space");
  expect(getCrawlerTenantWebsiteInventorySpaceLabel({ ...baseItem, space_name: null })).toBe(
    "News collection"
  );
  // Empty space + collection routes through the existing shared
  // "unknown workspace" copy used by the active inventory cell, so the
  // two surfaces stay consistent.
  expect(
    getCrawlerTenantWebsiteInventorySpaceLabel({
      ...baseItem,
      space_name: null,
      collection_name: null
    })
  ).toBe("Unknown workspace");
});

test("page <-> offset math is symmetric and clamps to non-negative ranges", () => {
  expect(offsetFromCrawlerTenantWebsiteInventoryPage(1, 25)).toBe(0);
  expect(offsetFromCrawlerTenantWebsiteInventoryPage(2, 25)).toBe(25);
  expect(offsetFromCrawlerTenantWebsiteInventoryPage(4, 50)).toBe(150);

  // out-of-range inputs clamp instead of returning NaN
  expect(offsetFromCrawlerTenantWebsiteInventoryPage(-3, 25)).toBe(0);
  expect(offsetFromCrawlerTenantWebsiteInventoryPage(2, 0)).toBe(0);

  expect(pageFromCrawlerTenantWebsiteInventoryOffset(0, 25)).toBe(1);
  expect(pageFromCrawlerTenantWebsiteInventoryOffset(25, 25)).toBe(2);
  expect(pageFromCrawlerTenantWebsiteInventoryOffset(150, 50)).toBe(4);
  expect(pageFromCrawlerTenantWebsiteInventoryOffset(-10, 25)).toBe(1);
});

test("page-size guard rejects values outside the published list", () => {
  expect(isCrawlerTenantWebsiteInventoryPageSize(25)).toBe(true);
  expect(isCrawlerTenantWebsiteInventoryPageSize(50)).toBe(true);
  expect(isCrawlerTenantWebsiteInventoryPageSize(100)).toBe(true);
  expect(isCrawlerTenantWebsiteInventoryPageSize(200)).toBe(false);
  expect(isCrawlerTenantWebsiteInventoryPageSize(7)).toBe(false);
  // The defaults file must keep the published list in sync with the guard.
  for (const size of CRAWLER_TENANT_WEBSITE_INVENTORY_PAGE_SIZES) {
    expect(isCrawlerTenantWebsiteInventoryPageSize(size)).toBe(true);
  }
});

test("crawler state query param omits the default and preserves server-side filters", () => {
  expect(getCrawlerTenantWebsiteInventoryCrawlerStateParam("all")).toBeUndefined();
  expect(getCrawlerTenantWebsiteInventoryCrawlerStateParam("healthy")).toBe("healthy");
  expect(getCrawlerTenantWebsiteInventoryCrawlerStateParam("backed_off")).toBe("backed_off");
  expect(getCrawlerTenantWebsiteInventoryCrawlerStateParam("auto_disabled")).toBe("auto_disabled");
});

test("tenantWebsiteInventory SDK method posts the right URL + method + query", async () => {
  // Stand up a stub client with a fetch spy, hand it to the SDK
  // factory, and call the new method. This protects the only handwritten
  // layer between the generated OpenAPI shape and the crawler admin UI.
  const fetch = vi.fn().mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const crawlerAdmin = initCrawlerAdmin({ fetch } as any);
  await crawlerAdmin.tenantWebsiteInventory({
    limit: 50,
    offset: 25,
    search: "example.com",
    update_interval: "weekly",
    crawler_state: "healthy",
    website_id: "12345678-1234-4234-8234-123456789abc",
    sort: "size_desc"
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith("/api/v1/admin/crawler/websites", {
    method: "get",
    params: {
      query: {
        limit: 50,
        offset: 25,
        search: "example.com",
        update_interval: "weekly",
        crawler_state: "healthy",
        website_id: "12345678-1234-4234-8234-123456789abc",
        sort: "size_desc"
      }
    }
  });
});

test("tenantWebsiteInventory SDK method accepts no params and forwards undefined", async () => {
  // The backend Query params are all optional with defaults; the SDK
  // should let the caller omit the entire object without triggering a
  // params-validation failure in the openapi-fetch layer.
  const fetch = vi.fn().mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const crawlerAdmin = initCrawlerAdmin({ fetch } as any);
  await crawlerAdmin.tenantWebsiteInventory();
  expect(fetch).toHaveBeenCalledWith("/api/v1/admin/crawler/websites", {
    method: "get",
    params: { query: undefined }
  });
});

test("action visibility: null candidate hides every button", () => {
  expect(getWebsiteDetailDialogActionVisibility({ candidate: null, hasActiveJob: false })).toEqual({
    retry: false,
    interval: false,
    reset: false,
    abort: false,
    delete: false
  });
  expect(getWebsiteDetailDialogActionVisibility({ candidate: null, hasActiveJob: true })).toEqual({
    retry: false,
    interval: false,
    reset: false,
    abort: false,
    delete: false
  });
});

test("action visibility: healthy candidate + no active job shows retry/interval/delete", () => {
  expect(
    getWebsiteDetailDialogActionVisibility({
      candidate: { ...baseItem, failure_state: null },
      hasActiveJob: false
    })
  ).toEqual({
    retry: true,
    interval: true,
    reset: false,
    abort: false,
    delete: true
  });
});

test("action visibility: healthy candidate + active job adds abort", () => {
  expect(
    getWebsiteDetailDialogActionVisibility({
      candidate: { ...baseItem, failure_state: null },
      hasActiveJob: true
    })
  ).toEqual({
    retry: true,
    interval: true,
    reset: false,
    abort: true,
    delete: true
  });
});

test("action visibility: BACKED_OFF candidate + no active job adds reset", () => {
  expect(
    getWebsiteDetailDialogActionVisibility({
      candidate: { ...baseItem, failure_state: "BACKED_OFF" },
      hasActiveJob: false
    })
  ).toEqual({
    retry: true,
    interval: true,
    reset: true,
    abort: false,
    delete: true
  });
});

test("action visibility: BACKED_OFF candidate + active job shows all destructive buttons", () => {
  expect(
    getWebsiteDetailDialogActionVisibility({
      candidate: { ...baseItem, failure_state: "BACKED_OFF" },
      hasActiveJob: true
    })
  ).toEqual({
    retry: true,
    interval: true,
    reset: true,
    abort: true,
    delete: true
  });
});

test("action visibility: AUTO_DISABLED candidate + no active job adds reset", () => {
  expect(
    getWebsiteDetailDialogActionVisibility({
      candidate: { ...baseItem, failure_state: "AUTO_DISABLED" },
      hasActiveJob: false
    })
  ).toEqual({
    retry: true,
    interval: true,
    reset: true,
    abort: false,
    delete: true
  });
});

test("action visibility: AUTO_DISABLED candidate + active job shows all destructive buttons", () => {
  // AUTO_DISABLED + active is rare in practice (the auto-disable
  // gate runs *after* a terminal outcome) but the visibility
  // function must still resolve correctly — the worker could be
  // mid-flight against a row that the operator paused on a previous
  // tab.
  expect(
    getWebsiteDetailDialogActionVisibility({
      candidate: { ...baseItem, failure_state: "AUTO_DISABLED" },
      hasActiveJob: true
    })
  ).toEqual({
    retry: true,
    interval: true,
    reset: true,
    abort: true,
    delete: true
  });
});
