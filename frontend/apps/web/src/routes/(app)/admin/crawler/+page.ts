import { CRAWLER_RECENT_FAILURES_DEFAULTS } from "$lib/features/admin/crawlerRecentFailures";

export const load = async (event) => {
  const { intric } = await event.parent();
  event.depends("admin:crawler-settings");
  event.depends("admin:crawler-recent-failures");

  const [crawlerSettings, recentFailuresResult] = await Promise.all([
    intric.settings.getCrawler(),
    intric.crawlerAdmin
      .recentFailures(CRAWLER_RECENT_FAILURES_DEFAULTS)
      .then((crawlerRecentFailures) => ({ ok: true as const, crawlerRecentFailures }))
      .catch(() => ({ ok: false as const }))
  ]);

  return {
    crawlerSettings,
    crawlerRecentFailuresWindowDays: CRAWLER_RECENT_FAILURES_DEFAULTS.days,
    crawlerRecentFailures: recentFailuresResult.ok
      ? recentFailuresResult.crawlerRecentFailures
      : null,
    crawlerRecentFailuresLoadFailed: !recentFailuresResult.ok
  };
};
