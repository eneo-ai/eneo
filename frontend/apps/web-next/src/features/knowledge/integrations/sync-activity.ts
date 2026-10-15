import type { IntegrationKnowledge } from "../knowledge";
import type { SyncLog, SyncLogWindow } from "./queries";

export type FileChange = { file: string; change: "added" | "updated" | "deleted" };

export type SyncLogExtras = {
  unchangedItems: number;
  /** The files the sync added, re-indexed or removed, capped by the writer. */
  changedFiles: FileChange[];
  /** Every change, also those the capped list leaves out. */
  changedTotal: number;
  /** The skipped list was capped; `skipped_items` still counts every skipped item. */
  skippedTruncated: boolean;
  reconcileWarning: string | null;
};

function asCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

function isFileChange(value: unknown): value is FileChange {
  const entry = value as Partial<FileChange> | null;
  return (
    typeof entry?.file === "string" &&
    (entry.change === "added" || entry.change === "updated" || entry.change === "deleted")
  );
}

// The sync writer stores these next to the counts the schema declares; they
// only exist for syncs run after the fields were introduced.
export function readSyncLogExtras(log: SyncLog): SyncLogExtras {
  const metadata = (log.metadata ?? {}) as Record<string, unknown>;
  const warning = metadata.reconcile_warning;
  const changedFiles = Array.isArray(metadata.changed_details)
    ? (metadata.changed_details as unknown[]).filter(isFileChange)
    : [];
  return {
    unchangedItems: asCount(metadata.unchanged_items),
    changedFiles,
    changedTotal: Math.max(asCount(metadata.changed_total), changedFiles.length),
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

const startedAt = (log: SyncLog) => new Date(log.started_at).getTime();

/**
 * Every item's loaded sync logs as one timeline, newest first. Each item is
 * loaded newest first and only partly, so the timeline stops where the first
 * partly loaded item runs out: below that point another item's older syncs
 * would be missing between the ones shown.
 */
export function mergeActivity(
  sources: readonly { item: IntegrationKnowledge; logs: readonly SyncLog[]; total?: number }[]
): ActivityEntry[] {
  let cutoff = -Infinity;
  for (const { logs, total } of sources) {
    if (logs.length === 0 || total === undefined || total <= logs.length) continue;
    cutoff = Math.max(cutoff, Math.min(...logs.map(startedAt)));
  }
  return sources
    .flatMap(({ item, logs }) => logs.map((log) => ({ log, item })))
    .filter((entry) => startedAt(entry.log) >= cutoff)
    .sort((a, b) => startedAt(b.log) - startedAt(a.log));
}

/**
 * The items whose next page can extend the merged timeline: those that hold the
 * cutoff (`mergeActivity`) and those with nothing loaded yet. Another partly
 * loaded item's older syncs already sit below the cutoff, so paging it would
 * show nothing until the cutoff moves past it.
 */
export function itemsToPage<Source extends { logs: readonly SyncLog[]; total: number }>(
  sources: readonly Source[]
): Source[] {
  const partial = sources.filter((source) => source.total > source.logs.length);
  const oldest = (source: Source) => Math.min(...source.logs.map(startedAt));
  const cutoff = Math.max(
    ...partial.filter((source) => source.logs.length > 0).map(oldest),
    -Infinity
  );
  return partial.filter((source) => source.logs.length === 0 || oldest(source) >= cutoff);
}

/**
 * An item's newest logs after reloading its first page. The older pages already
 * loaded are kept when the new page reaches them; otherwise more syncs ran than
 * a page holds, and keeping them would leave a gap.
 */
export function mergeFirstPage(
  loaded: readonly SyncLog[] | undefined,
  firstPage: readonly SyncLog[],
  total: number
): SyncLog[] {
  if (!loaded || loaded.length === 0 || firstPage.length >= total) return [...firstPage];
  const ids = new Set(firstPage.map((log) => log.id));
  if (!loaded.some((log) => ids.has(log.id))) return [...firstPage];
  return [...firstPage, ...loaded.filter((log) => !ids.has(log.id))];
}

/** An older page after the loaded logs; syncs that ran in between shift it, so drop repeats. */
export function appendPage(loaded: readonly SyncLog[], page: readonly SyncLog[]): SyncLog[] {
  const ids = new Set(loaded.map((log) => log.id));
  return [...loaded, ...page.filter((log) => !ids.has(log.id))];
}

/**
 * An item's window with an older page added, or null when the page does not
 * continue it. The page was read from where a window ending with the log
 * `after` stopped; syncs that ran since only shift it toward newer logs, so it
 * continues a window that still ends there or one whose last log it repeats.
 * A window that ends elsewhere (a new revision whose first page did not reach
 * the old end) would get a gap.
 */
export function continueWindow(
  loaded: SyncLogWindow,
  page: { items: readonly SyncLog[]; total_count: number },
  after: string | undefined
): SyncLogWindow | null {
  const last = loaded.logs.at(-1)?.id;
  if (last !== after && !page.items.some((log) => log.id === last)) return null;
  const logs = appendPage(loaded.logs, page.items);
  // Nothing new means the newest logs moved under the paging; stop rather than loop.
  return { logs, total: logs.length > loaded.logs.length ? page.total_count : logs.length };
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
  unchanged: number;
  deleted: number;
};

export function summarizeActivity(entries: readonly ActivityEntry[]): ActivityTotals {
  const totals: ActivityTotals = { syncs: 0, failed: 0, changedFiles: 0, unchanged: 0, deleted: 0 };
  for (const { log } of entries) {
    totals.syncs += 1;
    if (log.status === "error") totals.failed += 1;
    totals.changedFiles += asCount(log.files_processed) + asCount(log.pages_processed);
    totals.deleted += asCount(log.files_deleted);
    totals.unchanged += readSyncLogExtras(log).unchangedItems;
  }
  return totals;
}
