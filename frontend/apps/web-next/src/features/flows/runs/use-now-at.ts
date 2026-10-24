"use client";

import { useEffect, useState } from "react";

/** The longest delay a browser timer holds; a later deadline is waited for in steps. */
const MAX_TIMER_DELAY_MS = 2 ** 31 - 1;

/**
 * The time now, read again whenever `deadlines` (date-times; missing,
 * unreadable and past ones are left out) change and when the next of them
 * comes due: what a screen compares with a deadline flips exactly at it,
 * and nothing renders again in between.
 */
export function useNowAt(deadlines: readonly (string | null | undefined)[]): number {
  const [now, setNow] = useState(() => Date.now());
  const key = deadlines.map((deadline) => deadline ?? "").join("\n");
  useEffect(() => {
    const due = key
      .split("\n")
      .map((deadline) => Date.parse(deadline))
      .filter(Number.isFinite);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const arm = () => {
      const current = Date.now();
      setNow(current);
      const next = Math.min(...due.filter((at) => at > current));
      // Woken early, by the timer's limit or the browser, it waits on for the rest.
      if (Number.isFinite(next))
        timer = setTimeout(arm, Math.min(next - current, MAX_TIMER_DELAY_MS));
    };
    arm();
    return () => clearTimeout(timer);
  }, [key]);
  return now;
}
