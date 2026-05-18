import { CRAWLER_ACTIVE_INVENTORY_DEFAULTS } from "$lib/features/admin/crawlerActiveInventory";
import { CRAWLER_FAILURE_CLUSTERS_DEFAULTS } from "$lib/features/admin/crawlerFailureClusters";
import { CRAWLER_FAILURE_INVENTORY_DEFAULTS } from "$lib/features/admin/crawlerFailureInventory";
import { CRAWLER_TENANT_WEBSITE_INVENTORY_DEFAULTS } from "$lib/features/admin/crawlerTenantWebsiteInventory";
import { CRAWLER_WEBSITE_PROCESSING_DEFAULTS } from "$lib/features/admin/crawlerWebsiteProcessing";

export const load = async (event) => {
  const { intric } = await event.parent();
  event.depends("admin:crawler-settings");
  event.depends("admin:crawler-active-inventory");
  event.depends("admin:crawler-failure-inventory");
  event.depends("admin:crawler-failure-clusters");
  event.depends("admin:crawler-scheduled");
  event.depends("admin:crawler-website-processing");
  event.depends("admin:crawler-tenant-website-inventory");

  const [
    crawlerSettings,
    activeInventoryResult,
    failureInventoryResult,
    failureClustersResult,
    scheduledAggregateResult,
    websiteProcessingResult,
    tenantWebsiteInventoryResult
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
      .failureClusters(CRAWLER_FAILURE_CLUSTERS_DEFAULTS)
      .then((crawlerFailureClusters) => ({
        ok: true as const,
        crawlerFailureClusters
      }))
      .catch(() => ({ ok: false as const })),
    intric.crawlerAdmin
      .scheduledAggregate()
      .then((crawlerScheduledAggregate) => ({ ok: true as const, crawlerScheduledAggregate }))
      .catch(() => ({ ok: false as const })),
    intric.crawlerAdmin
      .websiteProcessingAggregate(CRAWLER_WEBSITE_PROCESSING_DEFAULTS)
      .then((crawlerWebsiteProcessing) => ({ ok: true as const, crawlerWebsiteProcessing }))
      .catch(() => ({ ok: false as const })),
    intric.crawlerAdmin
      .tenantWebsiteInventory(CRAWLER_TENANT_WEBSITE_INVENTORY_DEFAULTS)
      .then((crawlerTenantWebsiteInventory) => ({
        ok: true as const,
        crawlerTenantWebsiteInventory
      }))
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
    crawlerFailureClustersWindowDays: CRAWLER_FAILURE_CLUSTERS_DEFAULTS.days,
    crawlerFailureClusters: failureClustersResult.ok
      ? failureClustersResult.crawlerFailureClusters
      : null,
    crawlerFailureClustersLoadFailed: !failureClustersResult.ok,
    crawlerScheduledAggregate: scheduledAggregateResult.ok
      ? scheduledAggregateResult.crawlerScheduledAggregate
      : null,
    crawlerScheduledAggregateLoadFailed: !scheduledAggregateResult.ok,
    crawlerWebsiteProcessingWindowDays: CRAWLER_WEBSITE_PROCESSING_DEFAULTS.days,
    crawlerWebsiteProcessing: websiteProcessingResult.ok
      ? websiteProcessingResult.crawlerWebsiteProcessing
      : null,
    crawlerWebsiteProcessingLoadFailed: !websiteProcessingResult.ok,
    crawlerTenantWebsiteInventory: tenantWebsiteInventoryResult.ok
      ? tenantWebsiteInventoryResult.crawlerTenantWebsiteInventory
      : null,
    crawlerTenantWebsiteInventoryLoadFailed: !tenantWebsiteInventoryResult.ok
  };
};
