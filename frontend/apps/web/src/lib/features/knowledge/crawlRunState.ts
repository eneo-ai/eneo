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
    case "cancelled":
      return m.crawl_failure_cancelled();
    default:
      return m.crawl_failure_unknown();
  }
}

export function crawlRunFailureMessage(crawl: CrawlRun): string {
  return crawlFailureMessage(crawl.failure_code);
}
