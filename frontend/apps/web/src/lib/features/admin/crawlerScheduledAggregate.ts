import type { components } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";

export type CrawlerScheduledAggregateResponse =
  components["schemas"]["CrawlerScheduledAggregateResponse"];
export type CrawlerScheduledIntervalBucket =
  components["schemas"]["CrawlerScheduledIntervalBucket"];
export type CrawlerScheduledInterval = CrawlerScheduledIntervalBucket["update_interval"];

export function getCrawlerScheduledIntervalLabel(interval: CrawlerScheduledInterval): string {
  switch (interval) {
    case "daily":
      return m.crawler_scheduled_interval_daily();
    case "every_other_day":
      return m.crawler_scheduled_interval_every_other_day();
    case "weekly":
      return m.crawler_scheduled_interval_weekly();
    case "never":
      return m.crawler_scheduled_interval_never();
    default: {
      const exhaustive: never = interval;
      return exhaustive;
    }
  }
}

export function getCrawlerScheduledAggregateTotalLabel(
  aggregate: CrawlerScheduledAggregateResponse
): string {
  return m.crawler_scheduled_total({
    websites: formatCrawlerScheduledCount(aggregate.total_websites),
    size: formatCrawlerScheduledIndexedSize(aggregate.total_size_bytes)
  });
}

export function getCrawlerScheduledUnparseableLabel(
  aggregate: CrawlerScheduledAggregateResponse
): string | null {
  if (aggregate.unparseable_update_interval_website_count <= 0) {
    return null;
  }

  return m.crawler_scheduled_unparseable({
    count: formatCrawlerScheduledCount(aggregate.unparseable_update_interval_website_count)
  });
}

export function formatCrawlerScheduledCount(count: number): string {
  return new Intl.NumberFormat(getLocale(), {
    maximumFractionDigits: 0
  }).format(Math.max(Math.trunc(count), 0));
}

export function formatCrawlerScheduledIndexedSize(bytes: number): string {
  const wholeBytes = Math.max(Math.trunc(bytes), 0);
  const formatter = new Intl.NumberFormat(getLocale(), {
    maximumFractionDigits: 1
  });

  if (wholeBytes < 1024) {
    return `${formatter.format(wholeBytes)} ${m.crawler_unit_bytes()}`;
  }

  const kib = wholeBytes / 1024;
  if (kib < 1024) {
    return `${formatter.format(kib)} ${m.crawler_unit_kib()}`;
  }

  const mib = kib / 1024;
  if (mib < 1024) {
    return `${formatter.format(mib)} ${m.crawler_unit_mib()}`;
  }

  const gib = mib / 1024;
  if (gib < 1024) {
    return `${formatter.format(gib)} ${m.crawler_unit_gib()}`;
  }

  return `${formatter.format(gib / 1024)} ${m.crawler_unit_tib()}`;
}
