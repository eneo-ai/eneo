import type { AdminCrawlerScheduledWebsite } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

export type ScheduleSort = "next_due" | "last_crawled" | "url";
export type ScheduleState = AdminCrawlerScheduledWebsite["schedule_state"];

/** Sort direction is fixed per key by the server. */
export const sortDirections: Record<ScheduleSort, "ascending" | "descending"> = {
  next_due: "ascending",
  last_crawled: "descending",
  url: "ascending"
};

export function intervalLabel(interval: AdminCrawlerScheduledWebsite["update_interval"]): string {
  if (interval === "daily") return m.daily();
  if (interval === "every_other_day") return m.every_other_day();
  if (interval === "weekly") return m.weekly();
  return m.never();
}

/**
 * Relative distance from `asOf` to `target`, e.g. "in 20 minutes" or "2 hours ago".
 * Computed against the server's `as_of` so the hint does not drift between polls.
 */
export function relativeDue(target: string, asOf: string, locale: string): string {
  const minutes = Math.round((Date.parse(target) - Date.parse(asOf)) / 60_000);
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (Math.abs(minutes) < 60) return format.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 48) return format.format(hours, "hour");
  return format.format(Math.round(hours / 24), "day");
}
