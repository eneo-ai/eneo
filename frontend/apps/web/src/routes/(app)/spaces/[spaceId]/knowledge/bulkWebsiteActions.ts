import type { WebsiteBulkActionError } from "@eneo/eneo-js";

const MAX_WEBSITES_PER_REQUEST = 50;

type BulkError = Omit<WebsiteBulkActionError, "error"> & {
  error: WebsiteBulkActionError["error"] | "request_failed";
};

type BatchResult = {
  total: number;
  failed: number;
  errors: BulkError[];
};

type BatchSummary = BatchResult;

type RunBatchResult = {
  total: number;
  queued: number;
  failed: number;
  errors: BulkError[];
};

type StopBatchResult = {
  total: number;
  stopped: number;
  not_running: number;
  failed: number;
  errors: BulkError[];
};

type DeleteBatchResult = {
  total: number;
  deleted: number;
  not_found: number;
  failed: number;
  errors: BulkError[];
};

export type BulkRunSummary = RunBatchResult;

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

export function toggleVisibleWebsiteSelection(
  selectedWebsiteIds: ReadonlySet<string>,
  visibleWebsiteIds: Iterable<string>
): Set<string> {
  const visibleIds = Array.from(new Set(visibleWebsiteIds));
  const nextSelection = new Set(selectedWebsiteIds);
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((websiteId) => nextSelection.has(websiteId));

  for (const websiteId of visibleIds) {
    if (allVisibleSelected) {
      nextSelection.delete(websiteId);
    } else {
      nextSelection.add(websiteId);
    }
  }

  return nextSelection;
}

export function visibleWebsiteIdsFromTableRows(
  rows: Iterable<{ dataId?: string; isData: () => boolean }>
): string[] {
  const websiteIds: string[] = [];

  for (const row of rows) {
    if (row.isData() && row.dataId !== undefined) {
      websiteIds.push(row.dataId);
    }
  }

  return websiteIds;
}

export function bulkFailureWebsiteIds(errors: readonly BulkError[]): string[] {
  return Array.from(new Set(errors.map((error) => error.website_id)));
}

export function bulkDeletionWaitsForCrawlerCleanup(errors: readonly BulkError[]): boolean {
  return (
    errors.length > 0 &&
    errors.every(
      (error) => error.error === "crawl_stop_requested" || error.error === "crawl_cleanup_pending"
    )
  );
}

async function executeWebsiteBatches<Result extends BatchResult, Summary extends BatchSummary>(
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

export async function runWebsiteBatches(
  websiteIds: Iterable<string>,
  runBatch: (websiteIds: string[]) => Promise<RunBatchResult>
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

export async function stopWebsiteBatches(
  websiteIds: Iterable<string>,
  stopBatch: (websiteIds: string[]) => Promise<StopBatchResult>
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

export async function deleteWebsiteBatches(
  websiteIds: Iterable<string>,
  deleteBatch: (websiteIds: string[]) => Promise<DeleteBatchResult>
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
