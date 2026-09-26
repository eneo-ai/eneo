"use client";

import { useLocale } from "@astryxdesign/core/i18n";
import { Timestamp } from "@astryxdesign/core/Timestamp";
import { useHydrated } from "@/lib/hooks/use-hydrated";

export type ClientTimeFormat = "date" | "date_long" | "date_time" | "relative";

type AbsoluteFormat = Exclude<ClientTimeFormat, "relative">;

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
 * locale that renders only after hydration. Timestamp writes the date in the
 * viewer's time zone and a relative time against the viewer's clock, while
 * the server renders with its own, so server output would not match; until
 * hydration the cell stays empty. No hover card, so no extra tab stop: an
 * absolute format is the full information, and a relative one ("för 3
 * minuter sedan", kept current) is read out as its absolute time.
 *
 * @example
 * {run.created_at ? <ClientTime value={run.created_at} format="date_time" /> : "—"}
 */
export function ClientTime({ value, format }: { value: string; format: ClientTimeFormat }) {
  const hydrated = useHydrated();
  if (!hydrated) return null;
  return (
    <Timestamp
      value={value}
      format={format}
      type="inherit"
      color="inherit"
      hasTooltip={false}
      isLive={format === "relative"}
    />
  );
}

/**
 * The text ClientTime shows for an absolute format, for a name or label that
 * must say the same ("Fler åtgärder för 25 sep. 2026 09:30"). Null until
 * hydration, like ClientTime: the server does not know the viewer's time zone.
 * Also null without a valid value.
 */
export function useClientTimeText(
  value: string | null | undefined,
  format: AbsoluteFormat
): string | null {
  const hydrated = useHydrated();
  const locale = useLocale();
  const date = value ? new Date(value) : null;
  if (!hydrated || !date || Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, { ...TEXT_OPTIONS[format], calendar: "gregory" }).format(
    date
  );
}
