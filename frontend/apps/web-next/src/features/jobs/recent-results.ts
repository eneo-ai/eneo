"use client";

import { useSyncExternalStore } from "react";
import { jobResultInfoBlobId, type Job } from "./jobs";

/**
 * Info-blobs created by jobs that finished moments ago, so the file's row can
 * be pointed out when the refreshed list renders. Entries expire on their
 * own; nothing here persists across reloads.
 */
const HIGHLIGHT_MS = 8_000;

type Entry = { infoBlobId: string; until: number };

let entries: readonly Entry[] = [];
let snapshot: ReadonlySet<string> = new Set();
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setTimeout> | null = null;

function publish(): void {
  const now = Date.now();
  entries = entries.filter((entry) => entry.until > now);
  snapshot = new Set(entries.map((entry) => entry.infoBlobId));
  listeners.forEach((listener) => listener());
  if (timer !== null) clearTimeout(timer);
  timer = null;
  const soonest = entries.reduce((min, entry) => Math.min(min, entry.until), Infinity);
  if (soonest !== Infinity) timer = setTimeout(publish, Math.max(0, soonest - now));
}

/** Record the result of a finished job; a no-op for jobs without an info-blob. */
export function recordFinishedJob(job: Job, now = Date.now()): void {
  const infoBlobId = jobResultInfoBlobId(job);
  if (infoBlobId === null) return;
  entries = [...entries, { infoBlobId, until: now + HIGHLIGHT_MS }];
  publish();
}

/** Test seam: forget every recorded result. */
export function resetRecentResults(): void {
  entries = [];
  publish();
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
const EMPTY: ReadonlySet<string> = new Set();
const getSnapshot = () => snapshot;
const getServerSnapshot = () => EMPTY;

/** The ids of info-blobs that a job produced within the last few seconds. */
export function useRecentInfoBlobIds(): ReadonlySet<string> {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
