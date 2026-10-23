import type { Job } from "@eneo/eneo-js";
import { writable } from "svelte/store";

/** A full sync this person started whose worker has not reported on it yet. */
export type PendingSync = {
  jobId: string;
  knowledgeId: string;
  /** When it was queued; a jobs list sent before then may not hold the job yet. */
  queuedAt?: number;
};

/** A job missing from the list counts as settled only once it is at least this old. */
export const MISSING_JOB_GRACE_MS = 10_000;

/**
 * The syncs started on this page load that may still wait for a worker. The
 * item shows as queued until its progress appears or its job settles; after a
 * reload the progress polling alone tells.
 */
export const pendingSyncs = writable<PendingSync[]>([]);

/** An item's newest job is the one to wait for; an older pending sync of it is dropped. */
export function trackSyncs(items: PendingSync[], now = Date.now()): void {
  if (items.length === 0) return;
  pendingSyncs.update((current) => [
    ...current.filter((pending) => !items.some((item) => item.knowledgeId === pending.knowledgeId)),
    ...items.map((item) => ({ ...item, queuedAt: item.queuedAt ?? now }))
  ]);
}

export function untrackSyncs(jobIds: string[]): void {
  if (jobIds.length === 0) return;
  pendingSyncs.update((current) => current.filter((pending) => !jobIds.includes(pending.jobId)));
}

/**
 * The pending syncs whose job is over, or no longer listed at all. A missing job
 * only counts once the server's list has arrived (`jobsLoaded`) and the job is
 * old enough for that list to have been asked after it was queued.
 */
export function settledSyncs(
  pending: PendingSync[],
  jobs: Pick<Job, "id" | "status">[],
  jobsLoaded = true,
  now = Date.now()
): PendingSync[] {
  return pending.filter((item) => {
    const job = jobs.find((candidate) => candidate.id === item.jobId);
    if (!job) return jobsLoaded && now - (item.queuedAt ?? 0) >= MISSING_JOB_GRACE_MS;
    return job.status === "complete" || job.status === "failed";
  });
}

/**
 * The pending syncs the worker reports on now; their progress tells the rest. A
 * change notification's delta pass of the item is not the full sync queued here.
 */
export function reportedSyncs(
  pending: PendingSync[],
  progress: Readonly<Record<string, { sync_type?: string }>>
): PendingSync[] {
  return pending.filter((item) => {
    const entry = progress[item.knowledgeId];
    return entry !== undefined && entry.sync_type !== "delta";
  });
}
