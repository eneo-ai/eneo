import { expect, test, vi } from "vitest";
import { CRAWLER_ACTIVE_INVENTORY_DEFAULTS } from "$lib/features/admin/crawlerActiveInventory";
import { CRAWLER_RECENT_FAILURES_DEFAULTS } from "$lib/features/admin/crawlerRecentFailures";
import { load } from "../../../routes/(app)/admin/crawler/+page";

test("admin crawler load keeps settings available when diagnostics cannot be loaded", async () => {
  const crawlerSettings = { settings: { download_max_size: 10485760 } };
  const getCrawler = vi.fn().mockResolvedValue(crawlerSettings);
  const activeInventory = vi.fn().mockRejectedValue(new Error("active unavailable"));
  const recentFailures = vi.fn().mockRejectedValue(new Error("diagnostics unavailable"));
  const scheduledAggregate = vi.fn().mockRejectedValue(new Error("scheduled unavailable"));
  const depends = vi.fn();

  const result = await load({
    depends,
    parent: vi.fn().mockResolvedValue({
      intric: {
        settings: { getCrawler },
        crawlerAdmin: { activeInventory, recentFailures, scheduledAggregate }
      }
    })
  } as unknown as Parameters<typeof load>[0]);

  expect(depends).toHaveBeenCalledWith("admin:crawler-settings");
  expect(depends).toHaveBeenCalledWith("admin:crawler-active-inventory");
  expect(depends).toHaveBeenCalledWith("admin:crawler-recent-failures");
  expect(depends).toHaveBeenCalledWith("admin:crawler-scheduled");
  expect(getCrawler).toHaveBeenCalledOnce();
  expect(activeInventory).toHaveBeenCalledWith(CRAWLER_ACTIVE_INVENTORY_DEFAULTS);
  expect(recentFailures).toHaveBeenCalledWith(CRAWLER_RECENT_FAILURES_DEFAULTS);
  expect(scheduledAggregate).toHaveBeenCalledOnce();
  expect(result).toEqual({
    crawlerSettings,
    crawlerActiveInventory: null,
    crawlerActiveInventoryLoadFailed: true,
    crawlerRecentFailuresWindowDays: CRAWLER_RECENT_FAILURES_DEFAULTS.days,
    crawlerRecentFailures: null,
    crawlerRecentFailuresLoadFailed: true,
    crawlerScheduledAggregate: null,
    crawlerScheduledAggregateLoadFailed: true
  });
});

test("admin crawler load returns crawler diagnostics when both diagnostics calls succeed", async () => {
  const crawlerSettings = { settings: { download_max_size: 10485760 } };
  const crawlerActiveInventory = {
    total: 1,
    limit: 25,
    offset: 0,
    items: [
      {
        job_id: "11111111-1111-4111-8111-111111111111",
        crawl_run_id: "22222222-2222-4222-8222-222222222222",
        website_id: "12345678-1234-4234-8234-123456789abc",
        website_name: "Example active website",
        tenant_id: "33333333-3333-4333-8333-333333333333",
        tenant_display_name: "Tenant",
        status: "in progress",
        lifecycle_state: "running_with_progress",
        job_created_at: "2026-05-12T14:14:32.000Z",
        job_updated_at: "2026-05-12T14:14:50.000Z",
        crawl_run_created_at: "2026-05-12T14:14:33.000Z",
        pages_crawled: 3,
        files_downloaded: 1,
        pages_failed: 0,
        files_failed: 0,
        pages_source_retained: 0,
        pages_hash_retained: 0,
        files_hash_retained: 0,
        files_too_large_skipped: 0
      }
    ]
  };
  const crawlerRecentFailures = {
    total: 1,
    items: [
      {
        crawl_run_id: "22222222-2222-4222-8222-222222222222",
        job_id: "11111111-1111-4111-8111-111111111111",
        website_id: "12345678-1234-4234-8234-123456789abc",
        website_name: "Example website",
        tenant_id: "33333333-3333-4333-8333-333333333333",
        tenant_display_name: "Tenant",
        outcome_code: "CRAWL_NO_PAGES_RETURNED",
        failure_summary: null,
        finished_at: "2026-05-12T14:14:50.000Z",
        pages_crawled: 0,
        files_downloaded: 0,
        pages_failed: 0,
        files_failed: 0,
        pages_source_retained: 0,
        pages_hash_retained: 0,
        files_hash_retained: 0,
        files_too_large_skipped: 0
      }
    ]
  };
  const activeInventory = vi.fn().mockResolvedValue(crawlerActiveInventory);
  const recentFailures = vi.fn().mockResolvedValue(crawlerRecentFailures);
  const crawlerScheduledAggregate = {
    buckets: [
      { update_interval: "daily", website_count: 2, total_size_bytes: 1_048_576 },
      { update_interval: "every_other_day", website_count: 0, total_size_bytes: 0 },
      { update_interval: "never", website_count: 1, total_size_bytes: 500 },
      { update_interval: "weekly", website_count: 3, total_size_bytes: 1_536 }
    ],
    total_websites: 6,
    total_size_bytes: 1_050_612,
    unparseable_update_interval_website_count: 0,
    unparseable_update_interval_total_size_bytes: 0,
    tenant_id: "33333333-3333-4333-8333-333333333333"
  };
  const scheduledAggregate = vi.fn().mockResolvedValue(crawlerScheduledAggregate);

  const result = await load({
    depends: vi.fn(),
    parent: vi.fn().mockResolvedValue({
      intric: {
        settings: { getCrawler: vi.fn().mockResolvedValue(crawlerSettings) },
        crawlerAdmin: { activeInventory, recentFailures, scheduledAggregate }
      }
    })
  } as unknown as Parameters<typeof load>[0]);

  expect(activeInventory).toHaveBeenCalledWith(CRAWLER_ACTIVE_INVENTORY_DEFAULTS);
  expect(recentFailures).toHaveBeenCalledWith(CRAWLER_RECENT_FAILURES_DEFAULTS);
  expect(scheduledAggregate).toHaveBeenCalledOnce();
  expect(result).toEqual({
    crawlerSettings,
    crawlerActiveInventory,
    crawlerActiveInventoryLoadFailed: false,
    crawlerRecentFailuresWindowDays: CRAWLER_RECENT_FAILURES_DEFAULTS.days,
    crawlerRecentFailures,
    crawlerRecentFailuresLoadFailed: false,
    crawlerScheduledAggregate,
    crawlerScheduledAggregateLoadFailed: false
  });
});
