import type { Schema } from "@/lib/api/models";

/**
 * Bulk website actions (sync, stop, remove) over the /websites/bulk-*
 * endpoints, which take at most MAX_WEBSITES_PER_REQUEST ids: a selection is
 * sent in batches and the results are summed. Ported from apps/web's
 * bulkWebsiteActions.ts.
 */

export const MAX_WEBSITES_PER_REQUEST = 50;

type ApiBulkError = Schema<"WebsiteBulkActionError">;

/** A per-website failure; `request_failed` when the request itself failed. */
export type BulkError = Omit<ApiBulkError, "error"> & {
  error: ApiBulkError["error"] | "request_failed";
};

type BatchResult = { total: number; failed: number; errors: ApiBulkError[] };

export type BulkRunSummary = { total: number; queued: number; failed: number; errors: BulkError[] };

export type BulkStopSummary = {
  total: number;
  stopped: number;
  notRunning: number;
  failed: number;
  errors: BulkError[];
};

export type BulkDeleteSummary = {
  total: number;
  deleted: number;
  notFound: number;
  failed: number;
  errors: BulkError[];
};

function websiteIdBatches(websiteIds: Iterable<string>): string[][] {
  const uniqueIds = Array.from(new Set(websiteIds));
  const batches: string[][] = [];
  for (let start = 0; start < uniqueIds.length; start += MAX_WEBSITES_PER_REQUEST) {
    batches.push(uniqueIds.slice(start, start + MAX_WEBSITES_PER_REQUEST));
  }
  return batches;
}

/** The websites that failed, each once. */
export function bulkFailureWebsiteIds(errors: readonly BulkError[]): string[] {
  return Array.from(new Set(errors.map((error) => error.website_id)));
}

/** Every failure is the crawler stopping or cleaning up first: try again shortly. */
export function bulkDeletionWaitsForCrawlerCleanup(errors: readonly BulkError[]): boolean {
  return (
    errors.length > 0 &&
    errors.every(
      (error) => error.error === "crawl_stop_requested" || error.error === "crawl_cleanup_pending"
    )
  );
}

/**
 * Runs the batches in order and sums their results. When a request fails,
 * that batch and the ones after it count as failed (`request_failed`) and
 * the rest are not sent.
 */
async function executeWebsiteBatches<
  Result extends BatchResult,
  Summary extends { total: number; failed: number; errors: BulkError[] }
>(
  websiteIds: Iterable<string>,
  executeBatch: (websiteIds: string[]) => Promise<Result>,
  summary: Summary,
  mergeResult: (summary: Summary, result: Result) => void
): Promise<Summary> {
  const batches = websiteIdBatches(websiteIds);
  for (const [index, batch] of batches.entries()) {
    let result: Result;
    try {
      result = await executeBatch(batch);
    } catch {
      const remainingIds = batches.slice(index).flat();
      summary.total += remainingIds.length;
      summary.failed += remainingIds.length;
      summary.errors.push(
        ...remainingIds.map((websiteId): BulkError => ({
          website_id: websiteId,
          error: "request_failed"
        }))
      );
      break;
    }
    summary.total += result.total;
    summary.failed += result.failed;
    summary.errors.push(...result.errors);
    mergeResult(summary, result);
  }
  return summary;
}

export function runWebsiteBatches(
  websiteIds: Iterable<string>,
  runBatch: (websiteIds: string[]) => Promise<Schema<"BulkCrawlResponse">>
): Promise<BulkRunSummary> {
  return executeWebsiteBatches(
    websiteIds,
    runBatch,
    { total: 0, queued: 0, failed: 0, errors: [] },
    (summary, result) => {
      summary.queued += result.queued;
    }
  );
}

export function stopWebsiteBatches(
  websiteIds: Iterable<string>,
  stopBatch: (websiteIds: string[]) => Promise<Schema<"BulkCrawlStopResponse">>
): Promise<BulkStopSummary> {
  return executeWebsiteBatches(
    websiteIds,
    stopBatch,
    { total: 0, stopped: 0, notRunning: 0, failed: 0, errors: [] },
    (summary, result) => {
      summary.stopped += result.stopped;
      summary.notRunning += result.not_running;
    }
  );
}

export function deleteWebsiteBatches(
  websiteIds: Iterable<string>,
  deleteBatch: (websiteIds: string[]) => Promise<Schema<"BulkWebsiteDeleteResponse">>
): Promise<BulkDeleteSummary> {
  return executeWebsiteBatches(
    websiteIds,
    deleteBatch,
    { total: 0, deleted: 0, notFound: 0, failed: 0, errors: [] },
    (summary, result) => {
      summary.deleted += result.deleted;
      summary.notFound += result.not_found;
    }
  );
}
