import type { Schema } from "@/lib/api/models";

export type IntegrationSyncProgress = Schema<"IntegrationSyncProgress">;
export type SyncProgressFile = Schema<"IntegrationSyncProgressFile">;
export type SyncProgressPhase = IntegrationSyncProgress["phase"];

/** The running syncs of a space, keyed by integration knowledge id. */
export type ProgressById = Readonly<Record<string, IntegrationSyncProgress>>;

export type SyncProgressSummary = {
  phase: SyncProgressPhase;
  startedAt: string;
  /** Files in scope; null while any of the items does not know its own yet. */
  total: number | null;
  done: number;
  indexed: number;
  unchanged: number;
  skipped: number;
  /** Items of the source that are syncing right now. */
  syncing: number;
  /** Every running sync is a change notification's delta pass, started by nobody here. */
  background: boolean;
};

export const SYNC_PHASES: readonly SyncProgressPhase[] = ["discovering", "processing", "finishing"];

/** Several items' progress as one; the total is only known when every item knows its own. */
export function combineSyncProgress(
  entries: readonly IntegrationSyncProgress[]
): SyncProgressSummary | null {
  const [first] = entries;
  if (!first) return null;
  let total: number | null = 0;
  let done = 0;
  let indexed = 0;
  let unchanged = 0;
  let skipped = 0;
  let startedAt = first.started_at;
  // The source is as far along as its slowest item.
  let phaseIndex = SYNC_PHASES.length - 1;
  for (const entry of entries) {
    total = total === null || entry.total === null ? null : total + entry.total;
    done += entry.done;
    indexed += entry.indexed;
    unchanged += entry.unchanged;
    skipped += entry.skipped;
    if (new Date(entry.started_at).getTime() < new Date(startedAt).getTime()) {
      startedAt = entry.started_at;
    }
    phaseIndex = Math.min(phaseIndex, Math.max(0, SYNC_PHASES.indexOf(entry.phase)));
  }
  return {
    phase: SYNC_PHASES[phaseIndex] ?? "processing",
    startedAt,
    total,
    done,
    indexed,
    unchanged,
    skipped,
    syncing: entries.length,
    background: entries.every((entry) => entry.sync_type === "delta")
  };
}

/** Ids whose sync was running before and is gone now: their results are in the database. */
export function finishedSyncs(before: ProgressById, after: ProgressById): string[] {
  return Object.keys(before).filter((id) => !(id in after));
}
