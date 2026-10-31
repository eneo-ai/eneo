"use client";

import { useLocale } from "@astryxdesign/core/i18n";
import { Timestamp } from "@astryxdesign/core/Timestamp";

export type ClientTimeFormat = "date" | "date_long" | "date_time" | "relative" | "auto";

type AbsoluteFormat = Exclude<ClientTimeFormat, "relative" | "auto">;

/**
 * Timestamp's options for the absolute formats. Astryx exports no formatter,
 * so these mirror its formatInstant.ts; client-time.test.tsx checks that
 * useClientTimeText writes what ClientTime shows.
 */
const TEXT_OPTIONS: Record<AbsoluteFormat, Intl.DateTimeFormatOptions> = {
  date: { year: "numeric", month: "short", day: "numeric" },
  date_long: { year: "numeric", month: "long", day: "numeric" },
  date_time: { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }
};

/**
 * The one way to show a date or time: an Astryx Timestamp in the viewer's
 * locale and time zone, with relative time against the viewer's clock.
 * No hover card, so no extra tab stop: an
 * absolute format is the full information, and a relative one ("för 3
 * minuter sedan", kept current) is read out as its absolute time. "auto" is
 * Astryx's choice for lists: relative for the last week, the date and time
 * after that. A calendar date without a time (YYYY-MM-DD) is not an instant:
 * it goes through formatCalendarDate (lib/calendar-date.ts).
 *
 * @example
 * {run.created_at ? <ClientTime value={run.created_at} format="date_time" /> : "—"}
 */
export function ClientTime({ value, format }: { value: string; format: ClientTimeFormat }) {
  return (
    <Timestamp
      value={value}
      format={format}
      type="inherit"
      color="inherit"
      hasTooltip={false}
      isLive={format === "relative" || format === "auto"}
    />
  );
}

/**
 * The text ClientTime shows for an absolute format, for a name or label that
 * must say the same ("Fler åtgärder för 25 sep. 2026 09:30").
 * Null without a valid value.
 */
export function useClientTimeText(
  value: string | null | undefined,
  format: AbsoluteFormat
): string | null {
  const locale = useLocale();
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, { ...TEXT_OPTIONS[format], calendar: "gregory" }).format(
    date
  );
}
