"use client";

import { Timestamp } from "@astryxdesign/core/Timestamp";
import { useHydrated } from "@/lib/hooks/use-hydrated";

/**
 * An Astryx Timestamp that renders only after hydration. Timestamp writes the
 * date in the viewer's time zone and the server renders in its own, so the
 * server output would not match; until hydration the cell stays empty.
 * Absolute formats only: they carry no hover card and add no tab stop.
 */
export function ClientTime({ value, format }: { value: string; format: "date" | "date_long" }) {
  const hydrated = useHydrated();
  if (!hydrated) return null;
  return (
    <Timestamp value={value} format={format} type="inherit" color="inherit" hasTooltip={false} />
  );
}
