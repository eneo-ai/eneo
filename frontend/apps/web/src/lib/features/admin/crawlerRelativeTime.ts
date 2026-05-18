/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
 * See the LICENSE file at the repository root for the full license text.
 */

import { getLocale } from "$lib/paraglide/runtime";

export function createCrawlerRelativeTimeFormatter(): Intl.RelativeTimeFormat {
  const locale = getLocale() === "sv" ? "sv" : "en";
  return new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
}

const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const HOURS_PER_DAY = 24;
const DAYS_PER_MONTH = 30;
const MONTHS_PER_YEAR = 12;

export function formatCrawlerRelativeTime(
  relFormatter: Intl.RelativeTimeFormat,
  value: string | null,
  now: number = Date.now()
): string | null {
  if (!value) return null;
  const target = new Date(value).getTime();
  if (Number.isNaN(target)) return null;
  const diffMs = target - now;
  const seconds = Math.round(diffMs / 1000);
  if (Math.abs(seconds) < SECONDS_PER_MINUTE) {
    return relFormatter.format(seconds, "second");
  }
  const minutes = Math.round(seconds / SECONDS_PER_MINUTE);
  if (Math.abs(minutes) < MINUTES_PER_HOUR) {
    return relFormatter.format(minutes, "minute");
  }
  const hours = Math.round(minutes / MINUTES_PER_HOUR);
  if (Math.abs(hours) < HOURS_PER_DAY) {
    return relFormatter.format(hours, "hour");
  }
  const days = Math.round(hours / HOURS_PER_DAY);
  if (Math.abs(days) < DAYS_PER_MONTH) {
    return relFormatter.format(days, "day");
  }
  const months = Math.round(days / DAYS_PER_MONTH);
  if (Math.abs(months) < MONTHS_PER_YEAR) {
    return relFormatter.format(months, "month");
  }
  const years = Math.round(months / MONTHS_PER_YEAR);
  return relFormatter.format(years, "year");
}
