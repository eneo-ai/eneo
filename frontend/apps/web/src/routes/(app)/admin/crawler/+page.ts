import { CRAWLER_ACTIVE_INVENTORY_DEFAULTS } from "$lib/features/admin/crawlerActiveInventory";
import { CRAWLER_FAILURE_INVENTORY_DEFAULTS } from "$lib/features/admin/crawlerFailureInventory";
import { CRAWLER_RECENT_FAILURES_DEFAULTS } from "$lib/features/admin/crawlerRecentFailures";
import { CRAWLER_WEBSITE_PROCESSING_DEFAULTS } from "$lib/features/admin/crawlerWebsiteProcessing";

export const load = async (event) => {
  const { intric } = await event.parent();
  event.depends("admin:crawler-settings");
  event.depends("admin:crawler-active-inventory");
  event.depends("admin:crawler-failure-inventory");
  event.depends("admin:crawler-recent-failures");
  event.depends("admin:crawler-scheduled");
  event.depends("admin:crawler-website-processing");

  const [
    crawlerSettings,
    activeInventoryResult,
    failureInventoryResult,
    recentFailuresResult,
    scheduledAggregateResult,
    websiteProcessingResult
  ] = await Promise.all([
    intric.settings.getCrawler(),
    intric.crawlerAdmin
      .activeInventory(CRAWLER_ACTIVE_INVENTORY_DEFAULTS)
      .then((crawlerActiveInventory) => ({ ok: true as const, crawlerActiveInventory }))
      .catch(() => ({ ok: false as const })),
    intric.crawlerAdmin
      .failureInventory(CRAWLER_FAILURE_INVENTORY_DEFAULTS)
      .then((crawlerFailureInventory) => ({ ok: true as const, crawlerFailureInventory }))
      .catch(() => ({ ok: false as const })),
    intric.crawlerAdmin
      .recentFailures(CRAWLER_RECENT_FAILURES_DEFAULTS)
      .then((crawlerRecentFailures) => ({ ok: true as const, crawlerRecentFailures }))
      .catch(() => ({ ok: false as const })),
    intric.crawlerAdmin
      .scheduledAggregate()
      .then((crawlerScheduledAggregate) => ({ ok: true as const, crawlerScheduledAggregate }))
      .catch(() => ({ ok: false as const })),
    intric.crawlerAdmin
      .websiteProcessingAggregate(CRAWLER_WEBSITE_PROCESSING_DEFAULTS)
      .then((crawlerWebsiteProcessing) => ({ ok: true as const, crawlerWebsiteProcessing }))
      .catch(() => ({ ok: false as const }))
  ]);

  return {
    crawlerSettings,
    crawlerActiveInventory: activeInventoryResult.ok
      ? activeInventoryResult.crawlerActiveInventory
      : null,
    crawlerActiveInventoryLoadFailed: !activeInventoryResult.ok,
    crawlerFailureInventory: failureInventoryResult.ok
      ? failureInventoryResult.crawlerFailureInventory
      : null,
    crawlerFailureInventoryLoadFailed: !failureInventoryResult.ok,
    crawlerRecentFailuresWindowDays: CRAWLER_RECENT_FAILURES_DEFAULTS.days,
    crawlerRecentFailures: recentFailuresResult.ok
      ? recentFailuresResult.crawlerRecentFailures
      : null,
    crawlerRecentFailuresLoadFailed: !recentFailuresResult.ok,
    crawlerScheduledAggregate: scheduledAggregateResult.ok
      ? scheduledAggregateResult.crawlerScheduledAggregate
      : null,
    crawlerScheduledAggregateLoadFailed: !scheduledAggregateResult.ok,
    crawlerWebsiteProcessingWindowDays: CRAWLER_WEBSITE_PROCESSING_DEFAULTS.days,
    crawlerWebsiteProcessing: websiteProcessingResult.ok
      ? websiteProcessingResult.crawlerWebsiteProcessing
      : null,
    crawlerWebsiteProcessingLoadFailed: !websiteProcessingResult.ok
  };
};
