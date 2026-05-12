import type { CrawlRun, WebsiteSparse } from "@intric/intric-js";
import type { Label } from "@intric/ui";
import { m } from "$lib/paraglide/messages";

export type CrawlOutcomeCode =
  | "CRAWL_DUPLICATE_SKIPPED"
  | "CRAWL_NO_PAGES_RETURNED"
  | "CRAWL_SITEMAP_NO_PAGES"
  | "CRAWL_TIMEOUT_NO_PAGES"
  | "CRAWL_MAX_AGE_EXCEEDED"
  | "CRAWL_SOURCE_RETENTION_ONLY"
  | "CRAWL_ALL_UNCHANGED"
  | "CRAWL_PARTIAL_TIMEOUT"
  | "CRAWL_SHUTDOWN_ERROR"
  | "CRAWL_COMPLETED_WITH_PAGE_FAILURES"
  | "EMBEDDING_CONFIG_MISSING"
  | "UNKNOWN_CRAWL_ERROR";

export type CrawlOutcomeSeverity = "info" | "warning" | "error";

export type CrawlOutcome = {
  // Keep this open so unknown backend codes still render through the fallback path.
  code: CrawlOutcomeCode | string;
  severity: CrawlOutcomeSeverity;
  message_key: string;
  detail?: string | null;
  affected_count?: number | null;
  samples?: string[];
};

export type CrawlRunCountBreakdown = {
  pages_fetched: number;
  files_downloaded: number;
  pages_indexed: number;
  files_indexed: number;
  pages_hash_retained: number;
  files_hash_retained: number;
  pages_source_retained: number;
  pages_failed: number;
  files_failed: number;
};

export type CrawlRunResultLabel = {
  label: string;
  color: Label.LabelColor;
  tooltip?: string;
};

type CrawlRunWithOutcome = CrawlRun & {
  outcome?: CrawlOutcome | null;
  pages_source_retained?: number | null;
  pages_hash_retained?: number | null;
  files_hash_retained?: number | null;
  processing_summary?: CrawlRunCountBreakdown | null;
};

type WebsiteWithOutcome = WebsiteSparse & {
  latest_crawl?:
    | (NonNullable<WebsiteSparse["latest_crawl"]> & {
        outcome?: CrawlOutcome | null;
      })
    | null;
};

const outcomeLabels: Record<string, () => string> = {
  crawl_outcome_duplicate_skipped: () => m.crawl_outcome_duplicate_skipped(),
  crawl_outcome_embedding_config_missing: () => m.crawl_outcome_embedding_config_missing(),
  crawl_outcome_no_pages_returned: () => m.crawl_outcome_no_pages_returned(),
  crawl_outcome_sitemap_no_pages: () => m.crawl_outcome_sitemap_no_pages(),
  crawl_outcome_timeout_no_pages: () => m.crawl_outcome_timeout_no_pages(),
  crawl_outcome_partial_timeout: () => m.crawl_outcome_partial_timeout(),
  crawl_outcome_max_age_exceeded: () => m.crawl_outcome_max_age_exceeded(),
  crawl_outcome_source_retention_only: () => m.crawl_outcome_source_retention_only(),
  crawl_outcome_all_unchanged: () => m.crawl_outcome_all_unchanged(),
  crawl_outcome_shutdown_error: () => m.crawl_outcome_shutdown_error(),
  crawl_outcome_page_failures: () => m.crawl_outcome_page_failures(),
  crawl_outcome_unknown_error: () => m.crawl_outcome_unknown_error()
};

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
  return (crawl as CrawlRunWithOutcome).outcome ?? undefined;
}

export function getPagesSourceRetained(crawl: CrawlRun): number | undefined {
  const count = (crawl as CrawlRunWithOutcome).pages_source_retained;
  return typeof count === "number" && count > 0 ? count : undefined;
}

export function getCrawlRunCountBreakdown(crawl: CrawlRun): CrawlRunCountBreakdown {
  const crawlWithOutcome = crawl as CrawlRunWithOutcome;
  if (crawlWithOutcome.processing_summary) {
    return crawlWithOutcome.processing_summary;
  }

  const pagesFetched = positiveCount(crawl.pages_crawled);
  const filesDownloaded = positiveCount(crawl.files_downloaded);
  const pagesFailed = positiveCount(crawl.pages_failed);
  const filesFailed = positiveCount(crawl.files_failed);
  const pagesHashRetained = positiveCount(crawlWithOutcome.pages_hash_retained);
  const filesHashRetained = positiveCount(crawlWithOutcome.files_hash_retained);

  return {
    pages_fetched: pagesFetched,
    files_downloaded: filesDownloaded,
    pages_indexed: indexedCount(pagesFetched, pagesHashRetained, pagesFailed),
    files_indexed: indexedCount(filesDownloaded, filesHashRetained, filesFailed),
    pages_hash_retained: pagesHashRetained,
    files_hash_retained: filesHashRetained,
    pages_source_retained: positiveCount(crawlWithOutcome.pages_source_retained),
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
  return (website as WebsiteWithOutcome).latest_crawl?.outcome ?? undefined;
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
  return outcomeLabels[outcome.message_key]?.() ?? outcome.detail ?? fallback;
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
