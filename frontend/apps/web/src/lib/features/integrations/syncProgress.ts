// Response shape of GET /spaces/{id}/knowledge/integrations/sync-progress/;
// mirrors the backend's IntegrationSyncProgress model.
import type { SkipReasonCode } from "./skipReasons";

export type SyncProgressPhase = "discovering" | "processing" | "finishing";

export type SyncProgressFile = {
  name: string;
  outcome: "indexed" | "unchanged" | "skipped";
  reason?: string | null;
  code?: SkipReasonCode | null;
  params?: Record<string, string | number>;
  retry?: boolean;
};

export type IntegrationSyncProgress = {
  integration_knowledge_id: string;
  sync_type: "full" | "delta";
  phase: SyncProgressPhase;
  started_at: string;
  updated_at: string;
  /** Files in scope; null while the sync does not know it yet. */
  total: number | null;
  done: number;
  indexed: number;
  unchanged: number;
  skipped: number;
  deleted: number;
  /** The file or page being read now; absent from backends without the live feed. */
  current?: string | null;
  /** The latest finished files, newest first. */
  recent?: SyncProgressFile[];
};

export type SyncProgressSummary = {
  phase: SyncProgressPhase;
  startedAt: string;
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

const PHASE_ORDER: SyncProgressPhase[] = ["discovering", "processing", "finishing"];

/** Several items' progress as one; the total is only known when every item knows its own. */
export function combineSyncProgress(
  entries: readonly IntegrationSyncProgress[]
): SyncProgressSummary | null {
  if (entries.length === 0) return null;
  let total: number | null = 0;
  let done = 0;
  let indexed = 0;
  let unchanged = 0;
  let skipped = 0;
  let startedAt = entries[0].started_at;
  // The source is as far along as its slowest item.
  let phaseIndex = PHASE_ORDER.length - 1;
  for (const entry of entries) {
    total = total === null || entry.total === null ? null : total + entry.total;
    done += entry.done;
    indexed += entry.indexed;
    unchanged += entry.unchanged;
    skipped += entry.skipped;
    if (new Date(entry.started_at).getTime() < new Date(startedAt).getTime()) {
      startedAt = entry.started_at;
    }
    phaseIndex = Math.min(phaseIndex, Math.max(0, PHASE_ORDER.indexOf(entry.phase)));
  }
  return {
    phase: PHASE_ORDER[phaseIndex],
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

/** Share of the files done, 0–1; null when the total is unknown. */
export function progressFraction(summary: Pick<SyncProgressSummary, "done" | "total">) {
  if (summary.total === null || summary.total <= 0) return null;
  return Math.min(1, Math.max(0, summary.done / summary.total));
}
