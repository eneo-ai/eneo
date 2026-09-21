import type { CrawlRun } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

export type CrawlRunState =
  | "queued"
  | "running"
  | "finalizing"
  | "stopping"
  | "succeeded"
  | "unchanged"
  | "empty"
  | "partial"
  | "failed"
  | "cancelled"
  | "interrupted"
  | "unknown";

export function crawlRunState(crawl: CrawlRun): CrawlRunState {
  switch (crawl.phase) {
    case "pending_dispatch":
    case "queued":
      return "queued";
    case "running":
      return "running";
    case "finalizing":
      return "finalizing";
    case "stopping":
      return "stopping";
    case "terminal":
      return crawl.outcome ?? "unknown";
  }
}

export function isActiveCrawlRun(crawl: CrawlRun): boolean {
  return crawl.phase !== "terminal";
}

export function canRequestCrawlStop(crawl: CrawlRun): boolean {
  return isActiveCrawlRun(crawl) && crawl.phase !== "stopping";
}

export function isCompletedWithMissingResources(crawl: CrawlRun): boolean {
  return (
    crawl.phase === "terminal" &&
    crawl.outcome === "partial" &&
    crawl.failure_code === "resources_missing"
  );
}

/** Failed items may be at most this share of all items for a minor partial. */
export const MINOR_FAILURE_SHARE = 0.05;

const BENIGN_FAILURE_CODES = new Set([
  "resources_missing",
  "page_limit_reached",
  "content_skipped"
]);
const SEVERE_FAILURE_CODES = new Set([
  "tenant_quota_exceeded",
  "user_quota_exceeded",
  "remote_blocked",
  "remote_unreachable",
  "timed_out"
]);

/**
 * A partial crawl that reads as completed with notes rather than an issue.
 * Mirrors crawl_is_minor_partial on the backend: benign codes always, severe
 * codes never, otherwise the failed share of all items decides. Runs without
 * recorded counters cannot qualify.
 */
export function isMinorPartial(crawl: CrawlRun): boolean {
  if (crawl.phase !== "terminal" || crawl.outcome !== "partial") return false;
  const code = crawl.failure_code ?? null;
  if (code && BENIGN_FAILURE_CODES.has(code)) return true;
  if (code && SEVERE_FAILURE_CODES.has(code)) return false;
  const counters = [
    crawl.pages_crawled,
    crawl.pages_unchanged,
    crawl.files_downloaded,
    crawl.files_unchanged,
    crawl.pages_failed,
    crawl.files_failed
  ];
  if (counters.some((value) => value == null)) return false;
  const failed = (crawl.pages_failed ?? 0) + (crawl.files_failed ?? 0);
  const total =
    failed +
    (crawl.pages_crawled ?? 0) +
    (crawl.pages_unchanged ?? 0) +
    (crawl.files_downloaded ?? 0) +
    (crawl.files_unchanged ?? 0);
  return failed <= MINOR_FAILURE_SHARE * total;
}

export function hasCrawlIssues(crawl: CrawlRun): boolean {
  return (
    (crawl.pages_failed ?? 0) > 0 ||
    (crawl.files_failed ?? 0) > 0 ||
    ["partial", "failed", "interrupted", "unknown"].includes(crawlRunState(crawl))
  );
}

export function crawlRunStateLabel(state: CrawlRunState): string {
  switch (state) {
    case "queued":
      return m.queued();
    case "running":
      return m.in_progress();
    case "finalizing":
      return m.crawl_status_finalizing();
    case "stopping":
      return m.crawl_status_stopping();
    case "succeeded":
      return m.crawl_status_succeeded();
    case "unchanged":
      return m.crawl_status_unchanged();
    case "empty":
      return m.crawl_status_empty();
    case "partial":
      return m.crawl_completed_with_warnings();
    case "failed":
      return m.failed();
    case "cancelled":
      return m.crawl_status_cancelled();
    case "interrupted":
      return m.crawl_status_interrupted();
    case "unknown":
      return m.crawl_status_unknown();
  }
}

export function crawlFailureMessage(failureCode: string | null | undefined): string {
  switch (failureCode) {
    case "dispatch_failed":
      return m.crawl_failure_dispatch_failed();
    case "invalid_dispatch":
      return m.crawl_failure_invalid_dispatch();
    case "worker_interrupted":
      return m.crawl_failure_worker_interrupted();
    case "lease_expired":
      return m.crawl_failure_lease_expired();
    case "remote_unreachable":
      return m.crawl_failure_remote_unreachable();
    case "remote_blocked":
      return m.crawl_failure_remote_blocked();
    case "timed_out":
      return m.crawl_failure_timed_out();
    case "processing_failed":
      return m.crawl_failure_processing_failed();
    case "page_limit_reached":
      return m.crawl_failure_page_limit_reached();
    case "content_skipped":
      return m.crawl_failure_content_skipped();
    case "tenant_quota_exceeded":
      return m.crawl_failure_tenant_quota_exceeded();
    case "user_quota_exceeded":
      return m.crawl_failure_user_quota_exceeded();
    case "cancelled":
      return m.crawl_failure_cancelled();
    default:
      return m.crawl_failure_unknown();
  }
}

export function crawlRunFailureMessage(crawl: CrawlRun): string {
  if (isCompletedWithMissingResources(crawl)) return m.crawl_failure_resources_missing();
  if (crawl.failure_code === "page_limit_reached" || crawl.failure_code === "content_skipped") {
    return crawlFailureMessage(crawl.failure_code);
  }
  if (
    crawl.outcome === "partial" &&
    crawl.failure_code !== "tenant_quota_exceeded" &&
    crawl.failure_code !== "user_quota_exceeded"
  ) {
    return m.crawl_failure_partial();
  }
  return crawlFailureMessage(crawl.failure_code);
}

function normalizeFailureReason(reason: string): string {
  return reason
    .replace(/^_/, "")
    .replace(/([a-z])([A-Z])/g, "$1_$2")
    .toLowerCase();
}

export function crawlFailureReasonLabel(reason: string): string {
  const normalizedReason = normalizeFailureReason(reason);
  const labels: Record<string, () => string> = {
    processing_failed: () => m.failure_reason_PROCESSING_FAILED(),
    empty_content: () => m.failure_reason_EMPTY_CONTENT(),
    no_chunks: () => m.failure_reason_NO_CHUNKS(),
    embedding_timeout: () => m.failure_reason_EMBEDDING_TIMEOUT(),
    embedding_error: () => m.failure_reason_EMBEDDING_ERROR(),
    db_error: () => m.failure_reason_DB_ERROR(),
    tenant_quota_exceeded: () => m.failure_reason_TENANT_QUOTA_EXCEEDED(),
    user_quota_exceeded: () => m.failure_reason_USER_QUOTA_EXCEEDED(),
    no_embedding_model: () => m.failure_reason_NO_EMBEDDING_MODEL(),
    missing_provider: () => m.failure_reason_MISSING_PROVIDER(),
    redirect_rejected: () => m.failure_reason_redirect_rejected(),
    unsafe_target: () => m.failure_reason_unsafe_target(),
    request_timeout: () => m.failure_reason_timeout(),
    connection_error: () => m.failure_reason_connection(),
    response_decode_error: () => m.failure_reason_invalid_response(),
    request_failed: () => m.failure_reason_other(),
    invalid_sitemap: () => m.failure_reason_invalid_sitemap(),
    sitemap_too_large: () => m.failure_reason_too_large(),
    response_too_large: () => m.failure_reason_too_large(),
    file_too_large: () => m.failure_reason_too_large(),
    unsupported_content_type: () => m.failure_reason_unsupported_content(),
    robots_disallowed: () => m.failure_reason_robots_disallowed(),
    file_out_of_scope: () => m.failure_reason_file_out_of_scope()
  };
  if (normalizedReason === "http_404" || normalizedReason === "http_410") {
    return m.failure_reason_not_found({ status: normalizedReason.slice(5) });
  }
  if (/^http_\d{3}$/.test(normalizedReason)) {
    return m.failure_reason_http({ status: normalizedReason.slice(5) });
  }
  return labels[normalizedReason]?.() ?? m.failure_reason_other();
}

export function crawlFailureReasonHelp(reason: string): string | undefined {
  const normalizedReason = normalizeFailureReason(reason);
  if (/^http_5\d{2}$/.test(normalizedReason)) return m.crawl_failure_help_server();
  switch (normalizedReason) {
    case "http_404":
    case "http_410":
      return m.crawl_failure_help_not_found();
    case "http_401":
    case "http_403":
      return m.crawl_failure_help_access();
    case "http_429":
      return m.crawl_failure_help_rate_limit();
    case "redirect_rejected":
    case "file_out_of_scope":
      return m.crawl_failure_help_scope();
    case "robots_disallowed":
      return m.crawl_failure_help_robots();
    case "request_timeout":
    case "connection_error":
    case "embedding_timeout":
      return m.crawl_failure_help_temporary();
    case "tenant_quota_exceeded":
      return m.crawl_failure_tenant_quota_exceeded();
    case "user_quota_exceeded":
      return m.crawl_failure_user_quota_exceeded();
    default:
      return undefined;
  }
}
