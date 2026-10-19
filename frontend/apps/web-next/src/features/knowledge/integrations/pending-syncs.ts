"use client";

import { useSyncExternalStore } from "react";
import type { ProgressById } from "./sync-progress";

/** A full sync this person started whose worker has not reported on it yet. */
export type PendingSync = { jobId: string; knowledgeId: string };

/*
 * The syncs started on this page load that may still wait for a worker. The
 * item shows as queued until its progress appears (useSyncProgress) or its job
 * is over (JobsProvider); after a reload the progress polling alone tells.
 */
let pending: readonly PendingSync[] = [];
const listeners = new Set<() => void>();

function publish(next: readonly PendingSync[]): void {
  pending = next;
  listeners.forEach((listener) => listener());
}

export function pendingSyncs(): readonly PendingSync[] {
  return pending;
}

/** An item's newest job is the one to wait for; an older pending sync of it is dropped. */
export function trackSyncs(items: readonly PendingSync[]): void {
  if (items.length === 0) return;
  publish([
    ...pending.filter((entry) => !items.some((item) => item.knowledgeId === entry.knowledgeId)),
    ...items
  ]);
}

export function untrackSyncs(jobIds: readonly string[]): void {
  if (!pending.some((entry) => jobIds.includes(entry.jobId))) return;
  publish(pending.filter((entry) => !jobIds.includes(entry.jobId)));
}

/**
 * The pending syncs the worker reports on now; their progress tells the rest. A
 * change notification's delta pass of the item is not the full sync queued here.
 */
export function reportedSyncs(
  items: readonly PendingSync[],
  progress: ProgressById
): PendingSync[] {
  return items.filter((item) => {
    const entry = progress[item.knowledgeId];
    return entry !== undefined && entry.sync_type !== "delta";
  });
}

/** Test seam: forget every pending sync. */
export function resetPendingSyncs(): void {
  publish([]);
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
const NONE: readonly PendingSync[] = [];

export function usePendingSyncs(): readonly PendingSync[] {
  return useSyncExternalStore(subscribe, pendingSyncs, () => NONE);
}
