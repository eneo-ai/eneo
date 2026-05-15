import type { components } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";
import {
  getCrawlOutcomeLabel,
  type CrawlRunResultLabel
} from "$lib/features/knowledge/crawlOutcomePresentation";
import {
  getCrawlerTerminalOutcomeResultLabels,
  outcomeFromTerminalFeedItem
} from "$lib/features/admin/crawlerTerminalOutcomeFeed";

export type CrawlerWatchdogInterventionsResponse =
  components["schemas"]["CrawlerRecentFailuresResponse"];
export type CrawlerWatchdogInterventionItem = components["schemas"]["CrawlerRecentFailureItem"];
export const CRAWLER_WATCHDOG_INTERVENTIONS_DEFAULTS = {
  days: 7,
  limit: 5,
  offset: 0
} as const;

export function getCrawlerWatchdogInterventionWebsiteLabel(
  item: CrawlerWatchdogInterventionItem
): string {
  const websiteName = item.website_name?.trim();
  if (websiteName) {
    return websiteName;
  }

  return m.crawler_watchdog_interventions_unknown_website({
    id: item.website_id.slice(0, 8)
  });
}

export function getCrawlerWatchdogInterventionOutcomeLabel(
  item: CrawlerWatchdogInterventionItem
): string {
  return getCrawlOutcomeLabel(outcomeFromTerminalFeedItem(item), m.crawl_outcome_unknown_error());
}

export function getCrawlerWatchdogInterventionResultLabels(
  item: CrawlerWatchdogInterventionItem
): CrawlRunResultLabel[] {
  return getCrawlerTerminalOutcomeResultLabels(item);
}
