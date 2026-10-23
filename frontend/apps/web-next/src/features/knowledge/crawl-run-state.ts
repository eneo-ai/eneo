import type { CrawlRun } from "./knowledge";

/**
 * The crawler's run model (phase + outcome), ported from apps/web's
 * crawlRunState.ts. Every function returns translation keys or booleans; the
 * components call `t()`.
 */

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

export type CrawlFailureKind = "page" | "file";

const SKIPPED_PREFIX = "skipped duplicate crawl";

/**
 * Runs recorded before the crawler rewrite (and the test fixtures) carry only
 * the legacy `status`; the API fills `phase` for every run it serialises now.
 */
function legacyState(crawl: CrawlRun): CrawlRunState {
  switch (crawl.status) {
    case "queued":
      return "queued";
    case "in progress":
      return "running";
    case "complete":
      return (crawl.pages_failed ?? 0) > 0 || (crawl.files_failed ?? 0) > 0
        ? "partial"
        : "succeeded";
    case "failed":
      return crawl.result_location?.toLowerCase().startsWith(SKIPPED_PREFIX) === true
        ? "cancelled"
        : "failed";
    default:
      return "unknown";
  }
}

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
    default:
      return legacyState(crawl);
  }
}

const ACTIVE_STATES: ReadonlySet<CrawlRunState> = new Set([
  "queued",
  "running",
  "finalizing",
  "stopping"
]);

/** A crawl that can still change the website's indexed content. */
export function isActiveCrawlRun(crawl: CrawlRun): boolean {
  return ACTIVE_STATES.has(crawlRunState(crawl));
}

/** Active and not already asked to stop. */
export function canRequestCrawlStop(crawl: CrawlRun): boolean {
  return isActiveCrawlRun(crawl) && crawlRunState(crawl) !== "stopping";
}

/** A partial run whose only problem is that some addresses no longer exist. */
export function isCompletedWithMissingResources(crawl: CrawlRun): boolean {
  return crawlRunState(crawl) === "partial" && crawl.failure_code === "resources_missing";
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
  if (crawlRunState(crawl) !== "partial") return false;
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

const ISSUE_STATES: ReadonlySet<CrawlRunState> = new Set([
  "partial",
  "failed",
  "interrupted",
  "unknown"
]);

/** Something to look into: failed items, or an unsuccessful end state. */
export function hasCrawlIssues(crawl: CrawlRun): boolean {
  return (
    (crawl.pages_failed ?? 0) > 0 ||
    (crawl.files_failed ?? 0) > 0 ||
    ISSUE_STATES.has(crawlRunState(crawl))
  );
}

const STATE_LABEL_KEYS: Record<CrawlRunState, string> = {
  queued: "queued",
  running: "in_progress",
  finalizing: "crawl_status_finalizing",
  stopping: "crawl_status_stopping",
  succeeded: "crawl_status_succeeded",
  unchanged: "crawl_status_unchanged",
  empty: "crawl_status_empty",
  partial: "crawl_completed_with_warnings",
  failed: "failed",
  cancelled: "crawl_status_cancelled",
  interrupted: "crawl_status_interrupted",
  unknown: "crawl_status_unknown"
};

export function crawlRunStateLabelKey(state: CrawlRunState): string {
  return STATE_LABEL_KEYS[state];
}

const FAILURE_CODE_KEYS: Record<string, string> = {
  dispatch_failed: "crawl_failure_dispatch_failed",
  invalid_dispatch: "crawl_failure_invalid_dispatch",
  worker_interrupted: "crawl_failure_worker_interrupted",
  lease_expired: "crawl_failure_lease_expired",
  remote_unreachable: "crawl_failure_remote_unreachable",
  remote_blocked: "crawl_failure_remote_blocked",
  timed_out: "crawl_failure_timed_out",
  processing_failed: "crawl_failure_processing_failed",
  resources_missing: "crawl_failure_resources_missing",
  page_limit_reached: "crawl_failure_page_limit_reached",
  content_skipped: "crawl_failure_content_skipped",
  tenant_quota_exceeded: "crawl_failure_tenant_quota_exceeded",
  user_quota_exceeded: "crawl_failure_user_quota_exceeded",
  cancelled: "crawl_failure_cancelled"
};

export function crawlFailureMessageKey(failureCode: string | null | undefined): string {
  return (failureCode && FAILURE_CODE_KEYS[failureCode]) || "crawl_failure_unknown";
}

/** Why the run ended as it did, as a translation key; `null` for a run without a failure code. */
export function crawlRunFailureMessageKey(crawl: CrawlRun): string | null {
  if (!crawl.failure_code) return null;
  if (isCompletedWithMissingResources(crawl)) return "crawl_failure_resources_missing";
  if (crawl.failure_code === "page_limit_reached" || crawl.failure_code === "content_skipped") {
    return crawlFailureMessageKey(crawl.failure_code);
  }
  if (
    crawlRunState(crawl) === "partial" &&
    crawl.failure_code !== "tenant_quota_exceeded" &&
    crawl.failure_code !== "user_quota_exceeded"
  ) {
    return "crawl_failure_partial";
  }
  return crawlFailureMessageKey(crawl.failure_code);
}

/** "EMPTY_CONTENT", "_RedirectRejected" and "http_404" all read as snake_case. */
function normalizeFailureReason(reason: string): string {
  return reason
    .replace(/^_/, "")
    .replace(/([a-z])([A-Z])/g, "$1_$2")
    .toLowerCase();
}

const FAILURE_REASON_KEYS: Record<string, string> = {
  processing_failed: "failure_reason_PROCESSING_FAILED",
  empty_content: "failure_reason_EMPTY_CONTENT",
  no_chunks: "failure_reason_NO_CHUNKS",
  embedding_timeout: "failure_reason_EMBEDDING_TIMEOUT",
  embedding_error: "failure_reason_EMBEDDING_ERROR",
  db_error: "failure_reason_DB_ERROR",
  tenant_quota_exceeded: "failure_reason_TENANT_QUOTA_EXCEEDED",
  user_quota_exceeded: "failure_reason_USER_QUOTA_EXCEEDED",
  no_embedding_model: "failure_reason_NO_EMBEDDING_MODEL",
  missing_provider: "failure_reason_MISSING_PROVIDER",
  redirect_rejected: "failure_reason_redirect_rejected",
  unsafe_target: "failure_reason_unsafe_target",
  request_timeout: "failure_reason_timeout",
  connection_error: "failure_reason_connection",
  response_decode_error: "failure_reason_invalid_response",
  request_failed: "failure_reason_other",
  invalid_sitemap: "failure_reason_invalid_sitemap",
  sitemap_too_large: "failure_reason_too_large",
  response_too_large: "failure_reason_too_large",
  file_too_large: "failure_reason_too_large",
  unsupported_content_type: "failure_reason_unsupported_content",
  robots_disallowed: "failure_reason_robots_disallowed",
  file_out_of_scope: "failure_reason_file_out_of_scope"
};

type Translate = (key: string, values?: Record<string, string | number>) => string;

/** A failure reason code as text: "Sidan finns inte (404)", "Tom sida", … */
export function crawlFailureReasonLabel(t: Translate, reason: string): string {
  const normalized = normalizeFailureReason(reason);
  if (normalized === "http_404" || normalized === "http_410") {
    return t("failure_reason_not_found", { status: normalized.slice(5) });
  }
  if (/^http_\d{3}$/.test(normalized)) {
    return t("failure_reason_http", { status: normalized.slice(5) });
  }
  return t(FAILURE_REASON_KEYS[normalized] ?? "failure_reason_other");
}

const FAILURE_HELP_KEYS: Record<string, string> = {
  http_404: "crawl_failure_help_not_found",
  http_410: "crawl_failure_help_not_found",
  http_401: "crawl_failure_help_access",
  http_403: "crawl_failure_help_access",
  http_429: "crawl_failure_help_rate_limit",
  redirect_rejected: "crawl_failure_help_scope",
  file_out_of_scope: "crawl_failure_help_scope",
  robots_disallowed: "crawl_failure_help_robots",
  request_timeout: "crawl_failure_help_temporary",
  connection_error: "crawl_failure_help_temporary",
  embedding_timeout: "crawl_failure_help_temporary",
  tenant_quota_exceeded: "crawl_failure_tenant_quota_exceeded",
  user_quota_exceeded: "crawl_failure_user_quota_exceeded"
};

/** What to do about a failure reason, when there is something to say. */
export function crawlFailureReasonHelp(t: Translate, reason: string): string | undefined {
  const normalized = normalizeFailureReason(reason);
  if (/^http_5\d{2}$/.test(normalized)) return t("crawl_failure_help_server");
  const key = FAILURE_HELP_KEYS[normalized];
  return key ? t(key) : undefined;
}

/** An http(s) address a failed page or file can be opened at; undefined for anything else. */
export function resourceLink(url: string): string | undefined {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}
