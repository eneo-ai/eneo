import type { IntegrationKnowledge, Job } from "@eneo/eneo-js";
import { writable } from "svelte/store";
import { integrationDocumentsHref } from "./integrationDocuments";
import { summarizeIntegrationSync } from "./syncStatus";

/** An import whose first sync job is still running; reported once the job settles. */
export type PendingImport = {
  jobId: string;
  knowledgeId: string;
  name: string;
  spaceRouteId: string;
};

export const pendingImports = writable<PendingImport[]>([]);

export function trackImports(items: PendingImport[]): void {
  pendingImports.update((current) => [
    ...current.filter((pending) => !items.some((item) => item.jobId === pending.jobId)),
    ...items
  ]);
}

export function untrackImports(jobIds: string[]): void {
  pendingImports.update((current) => current.filter((pending) => !jobIds.includes(pending.jobId)));
}

/** The pending imports whose job finished, or is no longer reported at all. */
export function settledImports(
  pending: PendingImport[],
  jobs: Pick<Job, "id" | "status">[]
): PendingImport[] {
  return pending.filter((item) => {
    const job = jobs.find((candidate) => candidate.id === item.jobId);
    return !job || job.status === "complete" || job.status === "failed";
  });
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
