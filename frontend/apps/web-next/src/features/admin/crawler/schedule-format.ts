import type { ScheduleInterval, ScheduleSort } from "./crawler";

/** Sort direction is fixed per key by the server. */
export const SCHEDULE_SORT_DIRECTIONS: Record<ScheduleSort, "ascending" | "descending"> = {
  next_due: "ascending",
  last_crawled: "descending",
  url: "ascending"
};

const INTERVAL_KEYS: Record<ScheduleInterval, string> = {
  daily: "daily",
  every_other_day: "every_other_day",
  weekly: "weekly",
  never: "never"
};

/** Translation key of a crawl schedule interval. */
export function intervalLabelKey(interval: ScheduleInterval): string {
  return INTERVAL_KEYS[interval];
}

/**
 * Relative distance from `asOf` to `target`, e.g. "om 20 minuter" or "för 2
 * timmar sedan". Computed against the server's `as_of` so the hint does not
 * drift between polls.
 */
export function relativeDue(target: string, asOf: string, locale: string): string {
  const minutes = Math.round((Date.parse(target) - Date.parse(asOf)) / 60_000);
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (Math.abs(minutes) < 60) return format.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 48) return format.format(hours, "hour");
  return format.format(Math.round(hours / 24), "day");
}

/** Whole seconds between two instants as minutes and seconds, never negative. */
export function elapsedParts(from: string, until: string): { minutes: number; seconds: number } {
  const seconds = Math.max(0, Math.floor((Date.parse(until) - Date.parse(from)) / 1000));
  return { minutes: Math.floor(seconds / 60), seconds: seconds % 60 };
}
