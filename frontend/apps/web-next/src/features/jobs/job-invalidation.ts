import type { QueryClient } from "@tanstack/react-query";

/**
 * Query-key prefixes whose data a finished job can have changed. Invalidation
 * only refetches queries that are mounted, so listing a prefix nobody has on
 * screen costs nothing; forgetting one leaves a list stale until a reload.
 * Keep this list next to the query options it names (features/knowledge,
 * features/apps, …) when adding a kind of job.
 */
export const JOB_INVALIDATION_KEYS: readonly (readonly string[])[] = [
  // Space payloads carry knowledge counts, website states and app lists.
  ["spaces"],
  // Collection detail and its file list (uploads, text additions).
  ["collections"],
  // Website lists, run history and indexed pages (crawls).
  ["websites"],
  // Single info-blob reads and previews.
  ["info-blobs"],
  // App runs and their results.
  ["apps"],
  // Integration sync history (Confluence and SharePoint pulls).
  ["integrations"],
  // Tenant storage figures shown to admins (every upload moves them).
  ["storage"],
  // The signed-in user's quota, read by the upload dialog.
  ["users", "me"]
];

/** Refresh everything a finished or vanished job may have changed. */
export function invalidateAfterJobs(queryClient: QueryClient): void {
  for (const queryKey of JOB_INVALIDATION_KEYS) {
    void queryClient.invalidateQueries({ queryKey: [...queryKey] });
  }
}
