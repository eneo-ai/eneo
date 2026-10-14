import type { components, IntegrationKnowledge } from "@eneo/eneo-js";

export type SyncLog = components["schemas"]["SyncLog"];

export type SyncLogExtras = {
  unchangedItems: number;
  /** The skipped list was capped; `skipped_items` still counts every skipped item. */
  skippedTruncated: boolean;
  reconcileWarning: string | null;
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

export type ActivityKind = "failed" | "running" | "changed" | "unchanged";

export function activityKind(log: SyncLog): ActivityKind {
  if (log.status === "error") return "failed";
  if (log.status === "in_progress") return "running";
  const changed =
    asCount(log.files_processed) +
    asCount(log.pages_processed) +
    asCount(log.files_deleted) +
    asCount(log.skipped_items);
  return changed > 0 ? "changed" : "unchanged";
}

export type ActivityEntry = { log: SyncLog; item: IntegrationKnowledge };

/** Every item's sync logs as one timeline, newest first. */
export function mergeActivity(
  sources: readonly { item: IntegrationKnowledge; logs: readonly SyncLog[] }[]
): ActivityEntry[] {
  const entries = sources.flatMap(({ item, logs }) => logs.map((log) => ({ log, item })));
  return entries.sort(
    (a, b) => new Date(b.log.started_at).getTime() - new Date(a.log.started_at).getTime()
  );
}

export type ActivityDay = { day: string; entries: ActivityEntry[] };

function localDayKey(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** Entries grouped by the local calendar day they started; the order is kept. */
export function groupActivityByDay(entries: readonly ActivityEntry[]): ActivityDay[] {
  const days: ActivityDay[] = [];
  for (const entry of entries) {
    const day = localDayKey(entry.log.started_at);
    const current = days.at(-1);
    if (current?.day === day) current.entries.push(entry);
    else days.push({ day, entries: [entry] });
  }
  return days;
}

export type ActivityTotals = {
  syncs: number;
  failed: number;
  changedFiles: number;
  deleted: number;
};

export function summarizeActivity(entries: readonly ActivityEntry[]): ActivityTotals {
  const totals: ActivityTotals = { syncs: 0, failed: 0, changedFiles: 0, deleted: 0 };
  for (const { log } of entries) {
    totals.syncs += 1;
    if (log.status === "error") totals.failed += 1;
    totals.changedFiles += asCount(log.files_processed) + asCount(log.pages_processed);
    totals.deleted += asCount(log.files_deleted);
  }
  return totals;
}
