import type { components } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";

export type CrawlerUpdateInterval = components["schemas"]["UpdateInterval"];

export const CRAWLER_UPDATE_INTERVAL_OPTIONS: readonly CrawlerUpdateInterval[] = [
  "never",
  "daily",
  "every_other_day",
  "weekly"
] as const;

export function getCrawlerUpdateIntervalLabel(value: CrawlerUpdateInterval): string {
  switch (value) {
    case "never":
      return m.crawler_scheduled_interval_never();
    case "daily":
      return m.crawler_scheduled_interval_daily();
    case "every_other_day":
      return m.crawler_scheduled_interval_every_other_day();
    case "weekly":
      return m.crawler_scheduled_interval_weekly();
    default: {
      const exhaustive: never = value;
      return exhaustive;
    }
  }
}

export function isPausingTransition(
  current: CrawlerUpdateInterval,
  next: CrawlerUpdateInterval
): boolean {
  return current !== "never" && next === "never";
}

export function isResumingTransition(
  current: CrawlerUpdateInterval,
  next: CrawlerUpdateInterval
): boolean {
  return current === "never" && next !== "never";
}
