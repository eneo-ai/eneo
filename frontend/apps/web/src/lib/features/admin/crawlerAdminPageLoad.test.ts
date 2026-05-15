import { expect, test, vi } from "vitest";
import { CRAWLER_RECENT_FAILURES_DEFAULTS } from "$lib/features/admin/crawlerRecentFailures";
import { load } from "../../../routes/(app)/admin/crawler/+page";

test("admin crawler load keeps settings available when recent failures cannot be loaded", async () => {
  const crawlerSettings = { settings: { download_max_size: 10485760 } };
  const getCrawler = vi.fn().mockResolvedValue(crawlerSettings);
  const recentFailures = vi.fn().mockRejectedValue(new Error("diagnostics unavailable"));
  const depends = vi.fn();

  const result = await load({
    depends,
    parent: vi.fn().mockResolvedValue({
      intric: {
        settings: { getCrawler },
        crawlerAdmin: { recentFailures }
      }
    })
  } as unknown as Parameters<typeof load>[0]);

  expect(depends).toHaveBeenCalledWith("admin:crawler-settings");
  expect(depends).toHaveBeenCalledWith("admin:crawler-recent-failures");
  expect(getCrawler).toHaveBeenCalledOnce();
  expect(recentFailures).toHaveBeenCalledWith(CRAWLER_RECENT_FAILURES_DEFAULTS);
  expect(result).toEqual({
    crawlerSettings,
    crawlerRecentFailuresWindowDays: CRAWLER_RECENT_FAILURES_DEFAULTS.days,
    crawlerRecentFailures: null,
    crawlerRecentFailuresLoadFailed: true
  });
});

test("admin crawler load returns recent failures when diagnostics load succeeds", async () => {
  const crawlerSettings = { settings: { download_max_size: 10485760 } };
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
  const recentFailures = vi.fn().mockResolvedValue(crawlerRecentFailures);

  const result = await load({
    depends: vi.fn(),
    parent: vi.fn().mockResolvedValue({
      intric: {
        settings: { getCrawler: vi.fn().mockResolvedValue(crawlerSettings) },
        crawlerAdmin: { recentFailures }
      }
    })
  } as unknown as Parameters<typeof load>[0]);

  expect(recentFailures).toHaveBeenCalledWith(CRAWLER_RECENT_FAILURES_DEFAULTS);
  expect(result).toEqual({
    crawlerSettings,
    crawlerRecentFailuresWindowDays: CRAWLER_RECENT_FAILURES_DEFAULTS.days,
    crawlerRecentFailures,
    crawlerRecentFailuresLoadFailed: false
  });
});
