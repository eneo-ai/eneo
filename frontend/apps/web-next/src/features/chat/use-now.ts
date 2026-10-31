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

/** The viewer's current time, refreshed every minute. */
export function useNow(): number {
  return useSyncExternalStore(subscribe, getSnapshot);
}
