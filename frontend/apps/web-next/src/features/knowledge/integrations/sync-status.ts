import type { IntegrationKnowledge } from "../knowledge";

export type IntegrationSyncState = "never" | "success" | "error" | "empty";

export type IntegrationSyncSummary = {
  state: IntegrationSyncState;
  documentCount: number;
  lastSyncedAt: string | null;
  lastSyncAttemptedAt: string | null;
  error: string | null;
};

/** One item's latest sync, read from the health fields the sync records on it. */
export function summarizeIntegrationSync(knowledge: IntegrationKnowledge): IntegrationSyncSummary {
  const metadata = knowledge.metadata;
  const documentCount = metadata?.document_count ?? 0;
  const lastSyncedAt = metadata?.last_synced_at ?? null;
  const lastSyncAttemptedAt = metadata?.last_sync_attempted_at ?? null;
  const status = metadata?.last_sync_status ?? "never";

  if (status === "error") {
    return {
      state: "error",
      documentCount,
      lastSyncedAt,
      lastSyncAttemptedAt,
      error: metadata?.last_sync_error?.trim() ?? ""
    };
  }
  // Rows synced before the status column existed carry a timestamp but no status.
  if (status === "never" && lastSyncedAt === null) {
    return { state: "never", documentCount, lastSyncedAt, lastSyncAttemptedAt, error: null };
  }
  return {
    state: documentCount === 0 ? "empty" : "success",
    documentCount,
    lastSyncedAt,
    lastSyncAttemptedAt,
    error: null
  };
}

/** The later of two ISO timestamps; either may be missing. */
export function latestTime(a: string | null, b: string | null | undefined): string | null {
  if (!b) return a;
  if (!a) return b;
  return new Date(a).getTime() >= new Date(b).getTime() ? a : b;
}

/** Changes with every finished sync of the item: its document, skipped-file and log lists are then stale. */
export function syncRevision(knowledge: IntegrationKnowledge): string {
  const metadata = knowledge.metadata;
  return [
    metadata?.last_sync_attempted_at ?? "",
    metadata?.last_synced_at ?? "",
    metadata?.document_count ?? 0
  ].join("|");
}

function revisionTime(value: string | undefined): number {
  const time = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(time) ? Number.NEGATIVE_INFINITY : time;
}

/**
 * Orders two of an item's `syncRevision`s: positive when `a` is the newer, by
 * its latest sync attempt and then its latest successful sync.
 */
export function compareSyncRevisions(a: string, b: string): number {
  const [attemptedA, syncedA] = a.split("|");
  const [attemptedB, syncedB] = b.split("|");
  const order = (x: number, y: number) => (x === y ? 0 : x > y ? 1 : -1);
  return (
    order(revisionTime(attemptedA), revisionTime(attemptedB)) ||
    order(revisionTime(syncedA), revisionTime(syncedB))
  );
}
