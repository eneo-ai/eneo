import type { QueryClient } from "@tanstack/react-query";
import type { Job } from "@/features/jobs/jobs";
import { spaceQueryOptions, type Space } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { toast } from "@/lib/toast";
import type { IntegrationKnowledge } from "../knowledge";
import type { Translate } from "./skip-reasons";
import { itemHref } from "./sources";
import { summarizeIntegrationSync } from "./sync-status";

/** An import whose first sync job may still run; reported once the job is over. */
export type PendingImport = {
  jobId: string;
  knowledgeId: string;
  name: string;
  /** The space's route segment: its id, or "personal" / "organization". */
  spaceRouteId: string;
};

export const PENDING_IMPORTS_STORAGE_KEY = "eneo:pending-imports";

function isPendingImport(value: unknown): value is PendingImport {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return ["jobId", "knowledgeId", "name", "spaceRouteId"].every(
    (key) => typeof record[key] === "string"
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
 * The pending imports, mirrored into `storage` so a reload or a new tab within
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

// Read on first use: the server render has no sessionStorage.
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
  announce: (message: string) => void;
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

async function report(
  settled: readonly SettledImport[],
  { queryClient, t, announce, navigate }: ImportReportContext
): Promise<void> {
  // An earlier run may have reported some of them since.
  const pending = settled.filter((item) =>
    pendingImports().some((candidate) => candidate.jobId === item.jobId)
  );
  for (const routeId of new Set(pending.map((item) => item.spaceRouteId))) {
    const space = await readSpace(queryClient, routeId);
    const reported: string[] = [];
    const fail = (name: string, error: string | null) => {
      const message = t("integration_import_failed_toast", { name });
      toast.error(message, { description: error || undefined });
      announce(message);
    };
    for (const item of pending.filter((candidate) => candidate.spaceRouteId === routeId)) {
      const knowledge = space?.knowledge.integration_knowledge_list.items.find(
        (candidate) => candidate.id === item.knowledgeId && candidate.space_id === space.id
      );
      if (!knowledge) {
        // Deleted before its first sync was reported: nothing left to tell.
        reported.push(item.jobId);
        continue;
      }
      const outcome = describeImportOutcome(knowledge, routeId);
      if (!outcome.synced) {
        // A job that ended without the sync writing a status failed before it
        // got that far; one listed as complete may yet have one written.
        if (item.jobStatus === "complete") continue;
        fail(outcome.name, null);
        reported.push(item.jobId);
        continue;
      }
      reported.push(item.jobId);
      if (outcome.error !== null) {
        fail(outcome.name, outcome.error);
        continue;
      }
      const message = t("integration_import_result_toast", {
        name: outcome.name,
        indexed: outcome.indexed,
        skipped: outcome.skipped
      });
      toast.success(message, {
        duration: RESULT_TOAST_DURATION_MS,
        action: { label: t("show"), onClick: () => navigate(outcome.href) }
      });
      announce(message);
    }
    untrackImports(reported);
  }
}

let queue = Promise.resolve();

/**
 * Tells how each import's first sync went once its job is over, from the
 * item as its space holds it now: the documents indexed and skipped, with a
 * way to the source, or that the sync failed and why. Runs are serialised,
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
