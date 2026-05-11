import type { CrawlRun, WebsiteSparse } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";

export type CrawlOutcomeCode =
  | "CRAWL_DUPLICATE_SKIPPED"
  | "CRAWL_NO_PAGES_RETURNED"
  | "CRAWL_SITEMAP_NO_PAGES"
  | "CRAWL_TIMEOUT_NO_PAGES"
  | "CRAWL_MAX_AGE_EXCEEDED"
  | "CRAWL_SOURCE_RETENTION_ONLY"
  | "CRAWL_PARTIAL_TIMEOUT"
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

type CrawlRunWithOutcome = CrawlRun & {
  outcome?: CrawlOutcome | null;
  pages_source_retained?: number | null;
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
