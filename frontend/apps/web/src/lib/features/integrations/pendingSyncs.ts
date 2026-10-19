import type { Job } from "@eneo/eneo-js";
import { writable } from "svelte/store";

/** A full sync this person started whose worker has not reported on it yet. */
export type PendingSync = {
  jobId: string;
  knowledgeId: string;
};

/**
 * The syncs started on this page load that may still wait for a worker. The
 * item shows as queued until its progress appears or its job settles; after a
 * reload the progress polling alone tells.
 */
export const pendingSyncs = writable<PendingSync[]>([]);

/** An item's newest job is the one to wait for; an older pending sync of it is dropped. */
export function trackSyncs(items: PendingSync[]): void {
  if (items.length === 0) return;
  pendingSyncs.update((current) => [
    ...current.filter((pending) => !items.some((item) => item.knowledgeId === pending.knowledgeId)),
    ...items
  ]);
}

export function untrackSyncs(jobIds: string[]): void {
  if (jobIds.length === 0) return;
  pendingSyncs.update((current) => current.filter((pending) => !jobIds.includes(pending.jobId)));
}

/**
 * The pending syncs whose job is over, or no longer listed at all. A missing job
 * only counts once the server's list has arrived (`jobsLoaded`).
 */
export function settledSyncs(
  pending: PendingSync[],
  jobs: Pick<Job, "id" | "status">[],
  jobsLoaded = true
): PendingSync[] {
  return pending.filter((item) => {
    const job = jobs.find((candidate) => candidate.id === item.jobId);
    if (!job) return jobsLoaded;
    return job.status === "complete" || job.status === "failed";
  });
}

/** The pending syncs the worker reports on now; their progress tells the rest. */
export function reportedSyncs(
  pending: PendingSync[],
  progress: Readonly<Record<string, unknown>>
): PendingSync[] {
  return pending.filter((item) => item.knowledgeId in progress);
}
