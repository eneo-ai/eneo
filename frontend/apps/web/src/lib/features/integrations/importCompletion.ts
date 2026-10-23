import type { IntegrationKnowledge, Job } from "@eneo/eneo-js";
import { writable, type Writable } from "svelte/store";
import { integrationDocumentsHref } from "./integrationDocuments";
import { summarizeIntegrationSync } from "./syncStatus";

/** An import whose first sync job is still running; reported once the job settles. */
export type PendingImport = {
  jobId: string;
  knowledgeId: string;
  name: string;
  spaceRouteId: string;
  /** Imports queued together share one, and one notice once all of them have settled. */
  batchId?: string;
  /** What the notice for the batch calls it: the group's name. */
  batchName?: string;
};

export const PENDING_IMPORTS_STORAGE_KEY = "eneo:pending-imports";

function isPendingImport(value: unknown): value is PendingImport {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    ["jobId", "knowledgeId", "name", "spaceRouteId"].every(
      (key) => typeof record[key] === "string"
    ) &&
    ["batchId", "batchName"].every(
      (key) => record[key] === undefined || typeof record[key] === "string"
    )
  );
}

function readPendingImports(storage: Storage | null): PendingImport[] {
  try {
    const raw = storage?.getItem(PENDING_IMPORTS_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter(isPendingImport) : [];
  } catch {
    return [];
  }
}

/**
 * The pending imports, mirrored into `storage` so a reload or a new tab within
 * the job's lifetime still gets the promised notice. Storage failures leave the
 * list in memory only.
 */
export function createPendingImports(storage: Storage | null): Writable<PendingImport[]> {
  const store = writable<PendingImport[]>(readPendingImports(storage));
  store.subscribe((items) => {
    try {
      if (items.length === 0) storage?.removeItem(PENDING_IMPORTS_STORAGE_KEY);
      else storage?.setItem(PENDING_IMPORTS_STORAGE_KEY, JSON.stringify(items));
    } catch {
      // Quota or a blocked storage: the in-memory list still serves this page.
    }
  });
  return store;
}

function sessionStorageOrNull(): Storage | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

export const pendingImports = createPendingImports(sessionStorageOrNull());

export function trackImports(items: PendingImport[]): void {
  pendingImports.update((current) => [
    ...current.filter((pending) => !items.some((item) => item.jobId === pending.jobId)),
    ...items
  ]);
}

export function untrackImports(jobIds: string[]): void {
  pendingImports.update((current) => current.filter((pending) => !jobIds.includes(pending.jobId)));
}

/**
 * The pending imports whose job finished, or is no longer reported at all. A
 * missing job only counts once the server's list has arrived (`jobsLoaded`).
 */
export function settledImports(
  pending: PendingImport[],
  jobs: Pick<Job, "id" | "status">[],
  jobsLoaded = true
): PendingImport[] {
  return pending.filter((item) => {
    const job = jobs.find((candidate) => candidate.id === item.jobId);
    if (!job) return jobsLoaded;
    return job.status === "complete" || job.status === "failed";
  });
}

function batchOf(item: PendingImport): string {
  return item.batchId ?? item.jobId;
}

/**
 * The settled imports in the groups their notices are given in. A batch is held
 * back until every one of its imports has settled.
 */
export function reportableImports(
  pending: PendingImport[],
  settled: PendingImport[]
): PendingImport[][] {
  const groups = new Map<string, PendingImport[]>();
  for (const item of settled)
    groups.set(batchOf(item), [...(groups.get(batchOf(item)) ?? []), item]);
  return [...groups.entries()]
    .filter(
      ([batch, items]) => pending.filter((item) => batchOf(item) === batch).length === items.length
    )
    .map(([, items]) => items);
}

export type ImportOutcome = {
  name: string;
  /** Documents in the index after the sync, counting unchanged ones. */
  indexed: number;
  skipped: number;
  /** The documents page, or its skipped tab when nothing was indexed but files were skipped. */
  href: string;
  /** The sync's error text; null when it succeeded. */
  error: string | null;
  /** False while the item has not completed a sync attempt, so there is nothing to report yet. */
  synced: boolean;
};

function asCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

// The sync writer stores its counts in last_sync_summary; rows synced before
// the summary existed only carry document_count.
export function describeImportOutcome(
  knowledge: IntegrationKnowledge,
  spaceRouteId: string
): ImportOutcome {
  const summary = summarizeIntegrationSync(knowledge);
  const counts = (knowledge.metadata?.last_sync_summary ?? null) as Record<string, unknown> | null;
  const hasCounts = counts !== null && typeof counts.files_processed === "number";
  const indexed = hasCounts
    ? asCount(counts.files_processed) + asCount(counts.unchanged_items)
    : summary.documentCount;
  const skipped = hasCounts ? asCount(counts.skipped_total ?? counts.skipped_items) : 0;
  const tab = skipped > 0 && indexed === 0 ? "problems" : undefined;
  return {
    name: knowledge.name,
    indexed,
    skipped,
    href: integrationDocumentsHref(spaceRouteId, knowledge.id, tab),
    error: summary.state === "error" ? (summary.errors[0]?.message ?? "") : null,
    synced: summary.state !== "never"
  };
}
