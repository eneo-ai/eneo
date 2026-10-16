import type { components } from "@eneo/eneo-js";

export type SyncLog = components["schemas"]["SyncLog"];

export type SyncLogExtras = {
  unchangedItems: number;
  /** The skipped list was capped; `skipped_items` still counts every skipped item. */
  skippedTruncated: boolean;
  reconcileWarning: string | null;
};

export type SyncLogPageStats = {
  syncs: number;
  successful: number;
  files: number;
  deleted: number;
  pages: number;
};

function asCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

// The sync writer stores these next to the counts the schema declares; they
// only exist for syncs run after the fields were introduced.
export function readSyncLogExtras(log: SyncLog): SyncLogExtras {
  const metadata = (log.metadata ?? {}) as Record<string, unknown>;
  const warning = metadata.reconcile_warning;
  return {
    unchangedItems: asCount(metadata.unchanged_items),
    skippedTruncated: metadata.skipped_truncated === true,
    reconcileWarning: typeof warning === "string" && warning.trim() !== "" ? warning : null
  };
}

/** How many skipped items the capped list leaves out. */
export function skippedNotListed(log: SyncLog): number {
  return Math.max(0, asCount(log.skipped_items) - (log.skipped_details?.length ?? 0));
}

/** Totals over the loaded page only; the API does not report totals across pages. */
export function summarizeSyncLogPage(logs: readonly SyncLog[]): SyncLogPageStats {
  const stats: SyncLogPageStats = {
    syncs: logs.length,
    successful: 0,
    files: 0,
    deleted: 0,
    pages: 0
  };
  for (const log of logs) {
    if (log.status !== "success") continue;
    stats.successful += 1;
    stats.files += asCount(log.files_processed);
    stats.deleted += asCount(log.files_deleted);
    stats.pages += asCount(log.pages_processed);
  }
  return stats;
}
