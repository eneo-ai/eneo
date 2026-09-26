"use client";

import { Timestamp } from "@astryxdesign/core/Timestamp";
import { useHydrated } from "@/lib/hooks/use-hydrated";

export type ClientTimeFormat = "date" | "date_long" | "date_time" | "relative";

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
