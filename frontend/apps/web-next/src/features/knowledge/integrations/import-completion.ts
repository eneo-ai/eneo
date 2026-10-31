import type { QueryClient } from "@tanstack/react-query";
import type { Job } from "@/features/jobs/jobs";
import { spaceQueryOptions, type Space } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { toast } from "@/lib/toast";
import type { IntegrationKnowledge } from "../knowledge";
import type { Translate } from "./skip-reasons";
import { isCredentialsError } from "./source-problems";
import { itemHref, sourceHref } from "./sources";
import { summarizeIntegrationSync } from "./sync-status";

/** An import whose first sync job may still run; reported once the job is over. */
export type PendingImport = {
  jobId: string;
  knowledgeId: string;
  name: string;
  /** The space's route segment: its id, or "personal" / "organization". */
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

type PendingImports = {
  get: () => readonly PendingImport[];
  set: (items: readonly PendingImport[]) => void;
};

/**
 * The pending imports, mirrored into `storage` so a reload in the same tab within
 * the job's lifetime still gets the promised notice. Storage failures leave the
 * list in memory only.
 */
export function createPendingImports(storage: Storage | null): PendingImports {
  let items: readonly PendingImport[] = readPendingImports(storage);
  return {
    get: () => items,
    set: (next) => {
      items = next;
      try {
        if (next.length === 0) storage?.removeItem(PENDING_IMPORTS_STORAGE_KEY);
        else storage?.setItem(PENDING_IMPORTS_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // Quota or a blocked storage: the in-memory list still serves this page.
      }
    }
  };
}

function sessionStorageOrNull(): Storage | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

// Read on first use, including when browser storage is unavailable.
let store: PendingImports | null = null;
function pendingStore(): PendingImports {
  store ??= createPendingImports(sessionStorageOrNull());
  return store;
}

export function pendingImports(): readonly PendingImport[] {
  return pendingStore().get();
}

export function trackImports(items: readonly PendingImport[]): void {
  if (items.length === 0) return;
  const current = pendingStore().get();
  pendingStore().set([
    ...current.filter((pending) => !items.some((item) => item.jobId === pending.jobId)),
    ...items
  ]);
}

export function untrackImports(jobIds: readonly string[]): void {
  if (jobIds.length === 0) return;
  const current = pendingStore().get();
  pendingStore().set(current.filter((pending) => !jobIds.includes(pending.jobId)));
}

/** Test seam: read the pending imports from session storage again on next use. */
export function resetPendingImports(): void {
  store = null;
}

export type ImportOutcome = {
  name: string;
  /** Documents in the index after the sync, counting unchanged ones. */
  indexed: number;
  skipped: number;
  /** The source's page, on its Problems tab when nothing was indexed but files were skipped. */
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
  const counts = knowledge.metadata?.last_sync_summary ?? null;
  const hasCounts = counts !== null && typeof counts.files_processed === "number";
  const indexed = hasCounts
    ? asCount(counts.files_processed) + asCount(counts.unchanged_items)
    : summary.documentCount;
  const skipped = hasCounts ? asCount(counts.skipped_total ?? counts.skipped_items) : 0;
  return {
    name: knowledge.name,
    indexed,
    skipped,
    href: itemHref(spaceRouteId, knowledge, skipped > 0 && indexed === 0 ? "problems" : undefined),
    error: summary.state === "error" ? (summary.error ?? "") : null,
    synced: summary.state !== "never"
  };
}

/** A pending import whose job is over, with the job's status then (null: no longer listed). */
export type SettledImport = PendingImport & { jobStatus: Job["status"] | null };

export type ImportReportContext = {
  queryClient: QueryClient;
  t: Translate;
  navigate: (href: string) => void;
};

/** Long enough to reach the toast's action; hovering pauses it and its close button ends it. */
const RESULT_TOAST_DURATION_MS = 15_000;

async function readSpace(queryClient: QueryClient, routeId: string): Promise<Space | null> {
  try {
    return await queryClient.query({
      ...spaceQueryOptions(browserApi, routeId),
      staleTime: 0
    });
  } catch (error) {
    // The space is gone, or no longer this person's: nothing left to tell.
    const gone = error instanceof EneoApiError && (error.status === 403 || error.status === 404);
    if (gone) return null;
    throw error;
  }
}

function batchOf(item: PendingImport): string {
  return item.batchId ?? item.jobId;
}

/**
 * The settled imports in the groups their notices are given in. A batch is held
 * back until every one of its imports has settled.
 */
export function reportableImports<T extends PendingImport>(
  pending: readonly PendingImport[],
  settled: readonly T[]
): T[][] {
  const groups = new Map<string, T[]>();
  for (const item of settled)
    groups.set(batchOf(item), [...(groups.get(batchOf(item)) ?? []), item]);
  return [...groups.entries()]
    .filter(
      ([batch, items]) => pending.filter((item) => batchOf(item) === batch).length === items.length
    )
    .map(([, items]) => items);
}

type Result = { outcome: ImportOutcome; failed: boolean; wrapperId: string | null };

/** A group's outcomes, without deleted items; null while one of them may still get its status. */
function resultsOf(group: readonly SettledImport[], space: Space | null): Result[] | null {
  const results: Result[] = [];
  for (const item of group) {
    const knowledge = space?.knowledge.integration_knowledge_list.items.find(
      (candidate) => candidate.id === item.knowledgeId && candidate.space_id === space.id
    );
    // Deleted before its first sync was reported: nothing left to tell.
    if (!knowledge) continue;
    const outcome = describeImportOutcome(knowledge, item.spaceRouteId);
    // A job that ended without the sync writing a status failed before it got
    // that far; one listed as complete may yet have one written.
    if (!outcome.synced && item.jobStatus === "complete") return null;
    results.push({
      outcome,
      failed: !outcome.synced || outcome.error !== null,
      wrapperId: knowledge.wrapper_id ?? null
    });
  }
  return results;
}

async function report(
  settled: readonly SettledImport[],
  { queryClient, t, navigate }: ImportReportContext
): Promise<void> {
  // An earlier run may have reported some of them since.
  const pending = settled.filter((item) =>
    pendingImports().some((candidate) => candidate.jobId === item.jobId)
  );
  // The organisation's sign-in has a translated explanation; other sync errors have no code yet.
  const errorText = (error: string | null) =>
    !error
      ? null
      : isCredentialsError(error)
        ? t("integration_source_stopped_sign_in_description")
        : error;
  const show = (href: string) => ({ label: t("show"), onClick: () => navigate(href) });
  // The toaster's live region speaks each notice.
  const reportOne = ({ outcome, failed }: Result) => {
    if (failed) {
      toast.error(t("integration_import_failed_toast", { name: outcome.name }), {
        description: errorText(outcome.error) ?? undefined
      });
      return;
    }
    toast.success(
      t("integration_import_result_toast", {
        name: outcome.name,
        indexed: outcome.indexed,
        skipped: outcome.skipped
      }),
      { duration: RESULT_TOAST_DURATION_MS, action: show(outcome.href) }
    );
  };
  const reportBatch = (name: string, results: Result[], routeId: string) => {
    const wrapperId = results.find((result) => result.wrapperId)?.wrapperId ?? null;
    const href = (tab?: "problems") =>
      wrapperId
        ? sourceHref(routeId, { kind: "wrapper", id: wrapperId }, { tab })
        : `/spaces/${routeId}/knowledge?tab=integrations`;
    const failed = results.filter((result) => result.failed);
    if (failed.length > 0) {
      const details = new Set(failed.map((result) => errorText(result.outcome.error)));
      const [detail] = details;
      toast.error(
        t("integration_import_batch_failed_toast", {
          name,
          failed: failed.length,
          count: results.length
        }),
        {
          description: details.size === 1 && detail ? detail : undefined,
          action: show(href("problems"))
        }
      );
      return;
    }
    toast.success(
      t("integration_import_batch_result_toast", {
        name,
        count: results.length,
        indexed: results.reduce((sum, result) => sum + result.outcome.indexed, 0),
        skipped: results.reduce((sum, result) => sum + result.outcome.skipped, 0)
      }),
      { duration: RESULT_TOAST_DURATION_MS, action: show(href()) }
    );
  };

  for (const routeId of new Set(pending.map((item) => item.spaceRouteId))) {
    const groups = reportableImports(
      pendingImports(),
      pending.filter((item) => item.spaceRouteId === routeId)
    );
    if (groups.length === 0) continue;
    let space: Space | null;
    try {
      space = await readSpace(queryClient, routeId);
    } catch (error) {
      // One unavailable space must not starve reports for every other space.
      console.error("Could not read an import's result", error);
      continue;
    }
    const reported: string[] = [];
    for (const group of groups) {
      const results = resultsOf(group, space);
      if (results === null) continue;
      reported.push(...group.map((item) => item.jobId));
      const [first] = results;
      if (!first) continue;
      if (group.length === 1) reportOne(first);
      else reportBatch(group[0]?.batchName ?? first.outcome.name, results, routeId);
    }
    untrackImports(reported);
  }
}

let queue = Promise.resolve();

/**
 * Tells how each import's first sync went once its job is over, from the
 * item as its space holds it now: the documents indexed and skipped, with a
 * way to the source, or that the sync failed and why; an import of several
 * folders gets one notice once all of them have settled. Runs are serialised,
 * so two job snapshots close together never report an import twice; a run
 * that fails is logged and its imports wait for the next.
 */
export function reportImports(
  settled: readonly SettledImport[],
  context: ImportReportContext
): Promise<void> {
  queue = queue.then(() =>
    report(settled, context).catch((error: unknown) => {
      console.error("Could not report the result of an import", error);
    })
  );
  return queue;
}
