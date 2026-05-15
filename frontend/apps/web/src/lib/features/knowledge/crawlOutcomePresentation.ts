import type {
  CrawlOutcome,
  CrawlOutcomeCode,
  CrawlRun,
  CrawlRunProcessingSummary,
  WebsiteSparse
} from "@intric/intric-js";
import type { Label } from "@intric/ui";
import { m } from "$lib/paraglide/messages";

export type { CrawlOutcome, CrawlOutcomeCode, CrawlOutcomeSeverity } from "@intric/intric-js";

export type CrawlRunCountBreakdown = {
  [Key in keyof Required<CrawlRunProcessingSummary>]: number;
};

export type CrawlRunResultLabel = {
  label: string;
  color: Label.LabelColor;
  tooltip?: string;
};

const outcomeLabelsByCode = {
  CRAWL_DUPLICATE_SKIPPED: () => m.crawl_outcome_duplicate_skipped(),
  CRAWL_NO_PAGES_RETURNED: () => m.crawl_outcome_no_pages_returned(),
  CRAWL_SITEMAP_NO_PAGES: () => m.crawl_outcome_sitemap_no_pages(),
  CRAWL_TIMEOUT_NO_PAGES: () => m.crawl_outcome_timeout_no_pages(),
  CRAWL_MAX_AGE_EXCEEDED: () => m.crawl_outcome_max_age_exceeded(),
  CRAWL_RUNTIME_TIMEOUT: () => m.crawl_outcome_runtime_timeout(),
  CRAWL_QUEUE_ENQUEUE_FAILED: () => m.crawl_outcome_queue_enqueue_failed(),
  CRAWL_DIRECT_ENQUEUE_FAILED: () => m.crawl_outcome_direct_enqueue_failed(),
  CRAWL_SOURCE_RETENTION_ONLY: () => m.crawl_outcome_source_retention_only(),
  CRAWL_ALL_UNCHANGED: () => m.crawl_outcome_all_unchanged(),
  CRAWL_FILES_TOO_LARGE_ONLY: () => m.crawl_outcome_files_too_large_only(),
  CRAWL_PARTIAL_TIMEOUT: () => m.crawl_outcome_partial_timeout(),
  CRAWL_SHUTDOWN_ERROR: () => m.crawl_outcome_shutdown_error(),
  CRAWL_COMPLETED_WITH_PAGE_FAILURES: () => m.crawl_outcome_page_failures(),
  EMBEDDING_CONFIG_MISSING: () => m.crawl_outcome_embedding_config_missing(),
  UNKNOWN_CRAWL_ERROR: () => m.crawl_outcome_unknown_error()
} satisfies Record<CrawlOutcomeCode, () => string>;

const failureReasonLabels: Record<string, () => string> = {
  EMPTY_CONTENT: () => m.failure_reason_EMPTY_CONTENT(),
  NO_CHUNKS: () => m.failure_reason_NO_CHUNKS(),
  EMBEDDING_TIMEOUT: () => m.failure_reason_EMBEDDING_TIMEOUT(),
  EMBEDDING_ERROR: () => m.failure_reason_EMBEDDING_ERROR(),
  EMBEDDING_BATCH_LIMIT: () => m.failure_reason_EMBEDDING_BATCH_LIMIT(),
  DB_ERROR: () => m.failure_reason_DB_ERROR(),
  NO_EMBEDDING_MODEL: () => m.failure_reason_NO_EMBEDDING_MODEL(),
  MISSING_PROVIDER: () => m.failure_reason_MISSING_PROVIDER()
};

export function getCrawlOutcome(crawl: CrawlRun): CrawlOutcome | undefined {
  return crawl.outcome ?? undefined;
}

export function getPagesSourceRetained(crawl: CrawlRun): number | undefined {
  const count = crawl.pages_source_retained;
  return typeof count === "number" && count > 0 ? count : undefined;
}

export function getCrawlRunCountBreakdown(crawl: CrawlRun): CrawlRunCountBreakdown {
  if (crawl.processing_summary) {
    return countBreakdownFromSummary(crawl.processing_summary);
  }

  const pagesFetched = positiveCount(crawl.pages_crawled);
  const filesDownloaded = positiveCount(crawl.files_downloaded);
  const pagesFailed = positiveCount(crawl.pages_failed);
  const filesFailed = positiveCount(crawl.files_failed);
  const pagesHashRetained = positiveCount(crawl.pages_hash_retained);
  const filesHashRetained = positiveCount(crawl.files_hash_retained);
  const filesTooLargeSkipped = positiveCount(crawl.files_too_large_skipped);

  return {
    pages_fetched: pagesFetched,
    files_downloaded: filesDownloaded,
    pages_indexed: indexedCount(pagesFetched, pagesHashRetained, pagesFailed),
    files_indexed: indexedCount(filesDownloaded, filesHashRetained, filesFailed),
    pages_hash_retained: pagesHashRetained,
    files_hash_retained: filesHashRetained,
    files_too_large_skipped: filesTooLargeSkipped,
    pages_source_retained: positiveCount(crawl.pages_source_retained),
    pages_failed: pagesFailed,
    files_failed: filesFailed
  };
}

export function getCrawlRunResultLabels(crawl: CrawlRun): CrawlRunResultLabel[] {
  const breakdown = getCrawlRunCountBreakdown(crawl);
  const outcome = getCrawlOutcome(crawl);
  const labels: CrawlRunResultLabel[] = [];

  const fetchedResources = resourceLabel(breakdown.pages_fetched, breakdown.files_downloaded);
  if (fetchedResources) {
    labels.push({
      color: "blue",
      label: m.crawl_fetched_resources({ resources: fetchedResources })
    });
  }

  const indexedResources = resourceLabel(breakdown.pages_indexed, breakdown.files_indexed);
  if (indexedResources) {
    labels.push({
      color: "green",
      label: m.crawl_indexed_resources({ resources: indexedResources })
    });
  }

  const unchangedResources = resourceLabel(
    breakdown.pages_hash_retained,
    breakdown.files_hash_retained
  );
  if (unchangedResources) {
    labels.push({
      color: "moss",
      label: m.crawl_hash_retained_resources({ resources: unchangedResources }),
      tooltip:
        outcome?.code === "CRAWL_ALL_UNCHANGED"
          ? getCrawlOutcomeTooltip(outcome, m.crawl_outcome_all_unchanged())
          : undefined
    });
  }

  const sourceRetainedResources = pageResourceLabel(breakdown.pages_source_retained);
  if (sourceRetainedResources) {
    labels.push({
      color: "blue",
      label: m.crawl_source_retained_resources({
        resources: sourceRetainedResources
      })
    });
  }

  const tooLargeResources = fileResourceLabel(breakdown.files_too_large_skipped);
  if (tooLargeResources) {
    labels.push({
      color: "orange",
      label: m.crawl_too_large_skipped_resources({ resources: tooLargeResources }),
      tooltip: m.crawl_too_large_skipped_tooltip({
        resources: tooLargeResources
      })
    });
  }

  const failedResources = resourceLabel(breakdown.pages_failed, breakdown.files_failed);
  if (failedResources) {
    labels.push({
      color: "orange",
      label: m.crawl_failed_resources({ resources: failedResources }),
      tooltip: getFailureSummaryTooltip(crawl.failure_summary)
    });
  }

  return labels;
}

export function getLatestCrawlOutcome(website: WebsiteSparse): CrawlOutcome | undefined {
  return website.latest_crawl?.outcome ?? undefined;
}

export function isDuplicateCrawlSkip(outcome: CrawlOutcome | undefined): boolean {
  return outcome?.code === "CRAWL_DUPLICATE_SKIPPED";
}

export function isSourceRetentionOnly(
  outcome: CrawlOutcome | undefined
): outcome is CrawlOutcome & { code: "CRAWL_SOURCE_RETENTION_ONLY" } {
  return outcome?.code === "CRAWL_SOURCE_RETENTION_ONLY";
}

export function getCrawlOutcomeLabel(outcome: CrawlOutcome, fallback: string): string {
  return crawlOutcomeLabelForCode(outcome.code) ?? outcome.detail ?? fallback;
}

export function getCrawlRunFailureDetail(crawl: CrawlRun): string | undefined {
  const status = crawl.status?.toLowerCase();
  if (status !== "failed" && status !== "not found") {
    return undefined;
  }

  const outcome = getCrawlOutcome(crawl);
  const detail = normalizeDiagnosticDetail(outcome?.detail);
  if (detail) {
    return detail;
  }

  if (!outcome || outcome.code === "UNKNOWN_CRAWL_ERROR") {
    return m.crawl_missing_failure_detail();
  }

  return undefined;
}

export function getCrawlRunFailureTooltip(crawl: CrawlRun, fallback: string): string | undefined {
  const outcomeTooltip = getCrawlOutcomeTooltip(getCrawlOutcome(crawl), fallback);
  const failureDetail = getCrawlRunFailureDetail(crawl);
  if (!failureDetail) {
    return outcomeTooltip;
  }

  if (!outcomeTooltip) {
    return failureDetail;
  }

  return outcomeTooltip.includes(failureDetail)
    ? outcomeTooltip
    : `${outcomeTooltip}\n${failureDetail}`;
}

export function getSourceRetainedLabel(count: number): string {
  return m.source_retained_pages({ count });
}

export function getCrawlOutcomeTooltip(
  outcome: CrawlOutcome | undefined,
  fallback: string
): string | undefined {
  if (!outcome) {
    return undefined;
  }

  const label = getCrawlOutcomeLabel(outcome, fallback);
  const affected = outcome.affected_count
    ? `\n${m.crawl_outcome_affected_count({ count: outcome.affected_count })}`
    : "";
  const detail = outcome.detail ? `\n${outcome.detail}` : "";
  return `${label}${affected}${detail}`;
}

export function getFailureReasonLabel(reason: string): string {
  return failureReasonLabels[reason]?.() ?? reason;
}

export function getFailureSummaryTooltip(
  summary: Record<string, number> | null | undefined
): string | undefined {
  if (!summary || Object.keys(summary).length === 0) {
    return undefined;
  }

  const lines = Object.entries(summary)
    .map(([reason, count]) => `${getFailureReasonLabel(reason)}: ${count}`)
    .join("\n");

  return `${m.failure_reasons_tooltip()}:\n${lines}`;
}

function positiveCount(count: number | null | undefined): number {
  return typeof count === "number" && count > 0 ? count : 0;
}

function crawlOutcomeLabelForCode(code: string): string | undefined {
  // Backend can emit a new outcome code before the frontend schema is regenerated.
  if (code in outcomeLabelsByCode) {
    return outcomeLabelsByCode[code as CrawlOutcomeCode]();
  }

  return undefined;
}

function countBreakdownFromSummary(summary: CrawlRunProcessingSummary): CrawlRunCountBreakdown {
  return {
    pages_fetched: positiveCount(summary.pages_fetched),
    files_downloaded: positiveCount(summary.files_downloaded),
    pages_indexed: positiveCount(summary.pages_indexed),
    files_indexed: positiveCount(summary.files_indexed),
    pages_hash_retained: positiveCount(summary.pages_hash_retained),
    files_hash_retained: positiveCount(summary.files_hash_retained),
    files_too_large_skipped: positiveCount(summary.files_too_large_skipped),
    pages_source_retained: positiveCount(summary.pages_source_retained),
    pages_failed: positiveCount(summary.pages_failed),
    files_failed: positiveCount(summary.files_failed)
  };
}

function normalizeDiagnosticDetail(detail: string | null | undefined): string | undefined {
  const trimmed = detail?.trim();
  return trimmed ? trimmed : undefined;
}

function indexedCount(total: number, hashRetained: number, failed: number): number {
  return Math.max(total - hashRetained - failed, 0);
}

function resourceLabel(pages: number, files: number): string | undefined {
  const parts = [pageResourceLabel(pages), fileResourceLabel(files)].filter(
    (part): part is string => Boolean(part)
  );

  if (parts.length === 0) {
    return undefined;
  }

  if (parts.length === 1) {
    return parts[0];
  }

  return m.crawl_resource_join({ left: parts[0], right: parts[1] });
}

function pageResourceLabel(count: number): string | undefined {
  if (count <= 0) {
    return undefined;
  }

  return count === 1
    ? m.crawl_resource_page_one({ count })
    : m.crawl_resource_page_other({ count });
}

function fileResourceLabel(count: number): string | undefined {
  if (count <= 0) {
    return undefined;
  }

  return count === 1
    ? m.crawl_resource_file_one({ count })
    : m.crawl_resource_file_other({ count });
}
