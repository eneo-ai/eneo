import { CRAWLER_ACTIVE_INVENTORY_DEFAULTS } from "$lib/features/admin/crawlerActiveInventory";
import { CRAWLER_RECENT_FAILURES_DEFAULTS } from "$lib/features/admin/crawlerRecentFailures";

export const load = async (event) => {
  const { intric } = await event.parent();
  event.depends("admin:crawler-settings");
  event.depends("admin:crawler-active-inventory");
  event.depends("admin:crawler-recent-failures");

  const [crawlerSettings, activeInventoryResult, recentFailuresResult] = await Promise.all([
    intric.settings.getCrawler(),
    intric.crawlerAdmin
      .activeInventory(CRAWLER_ACTIVE_INVENTORY_DEFAULTS)
      .then((crawlerActiveInventory) => ({ ok: true as const, crawlerActiveInventory }))
      .catch(() => ({ ok: false as const })),
    intric.crawlerAdmin
      .recentFailures(CRAWLER_RECENT_FAILURES_DEFAULTS)
      .then((crawlerRecentFailures) => ({ ok: true as const, crawlerRecentFailures }))
      .catch(() => ({ ok: false as const }))
  ]);

  return {
    crawlerSettings,
    crawlerActiveInventory: activeInventoryResult.ok
      ? activeInventoryResult.crawlerActiveInventory
      : null,
    crawlerActiveInventoryLoadFailed: !activeInventoryResult.ok,
    crawlerRecentFailuresWindowDays: CRAWLER_RECENT_FAILURES_DEFAULTS.days,
    crawlerRecentFailures: recentFailuresResult.ok
      ? recentFailuresResult.crawlerRecentFailures
      : null,
    crawlerRecentFailuresLoadFailed: !recentFailuresResult.ok
  };
};
