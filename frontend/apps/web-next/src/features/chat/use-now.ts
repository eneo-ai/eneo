"use client";

import { useSyncExternalStore } from "react";

const MINUTE = 60_000;
const listeners = new Set<() => void>();
let cachedNow: number | null = null;
let timer: ReturnType<typeof setInterval> | null = null;

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (timer === null) {
    timer = setInterval(() => {
      cachedNow = Date.now();
      for (const notify of listeners) notify();
    }, MINUTE);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
      cachedNow = null;
    }
  };
}

function getSnapshot(): number {
  if (cachedNow === null) cachedNow = Date.now();
  return cachedNow;
}

function getServerSnapshot(): null {
  return null;
}

/**
 * The current time, refreshed every minute; `null` on the server and during
 * hydration so time-dependent text (greeting, "Idag 09:42") never mismatches
 * the server markup. Render a time-neutral fallback while it is null.
 */
export function useNow(): number | null {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
