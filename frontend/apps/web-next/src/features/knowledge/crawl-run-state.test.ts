import { describe, expect, it } from "vitest";
import {
  canRequestCrawlStop,
  crawlFailureReasonHelp,
  crawlFailureReasonLabel,
  crawlRunFailureMessageKey,
  crawlRunState,
  hasCrawlIssues,
  isActiveCrawlRun,
  isCompletedWithMissingResources,
  isMinorPartial,
  resourceLink
} from "./crawl-run-state";
import type { CrawlRun } from "./knowledge";

function run(overrides: Partial<CrawlRun> = {}): CrawlRun {
  return {
    id: "run-1",
    status: "complete",
    phase: "terminal",
    outcome: "succeeded",
    origin: "manual",
    pages_crawled: 10,
    pages_unchanged: 0,
    files_downloaded: 0,
    files_unchanged: 0,
    pages_failed: 0,
    files_failed: 0,
    failure_summary: null,
    failure_code: null,
    failure_detail: null,
    result_location: null,
    finished_at: "2026-09-10T09:00:00Z",
    cancel_requested_at: null,
    attempt_count: 1,
    ...overrides
  };
}

const t = (key: string, values: Record<string, string | number> = {}) =>
  `${key}(${Object.entries(values)
    .map(([name, value]) => `${name}=${value}`)
    .join(",")})`;

describe("crawlRunState", () => {
  it("reads the phase, and the outcome once terminal", () => {
    expect(crawlRunState(run({ phase: "pending_dispatch", outcome: null }))).toBe("queued");
    expect(crawlRunState(run({ phase: "running", outcome: null }))).toBe("running");
    expect(crawlRunState(run({ phase: "stopping", outcome: null }))).toBe("stopping");
    expect(crawlRunState(run({ outcome: "cancelled" }))).toBe("cancelled");
    expect(crawlRunState(run({ outcome: null }))).toBe("unknown");
  });

  it("falls back to the legacy status for runs without a phase", () => {
    const legacy = (status: CrawlRun["status"], extra: Partial<CrawlRun> = {}) =>
      crawlRunState({ ...run({ status, ...extra }), phase: undefined as never, outcome: null });
    expect(legacy("in progress")).toBe("running");
    expect(legacy("complete")).toBe("succeeded");
    expect(legacy("complete", { pages_failed: 2 })).toBe("partial");
    expect(legacy("failed")).toBe("failed");
    expect(legacy("failed", { result_location: "Skipped duplicate crawl" })).toBe("cancelled");
  });

  it("knows which runs are active and can still be stopped", () => {
    expect(isActiveCrawlRun(run({ phase: "queued", outcome: null }))).toBe(true);
    expect(canRequestCrawlStop(run({ phase: "running", outcome: null }))).toBe(true);
    expect(canRequestCrawlStop(run({ phase: "stopping", outcome: null }))).toBe(false);
    expect(isActiveCrawlRun(run())).toBe(false);
  });
});

describe("isMinorPartial", () => {
  const partial = (overrides: Partial<CrawlRun>) => run({ outcome: "partial", ...overrides });

  it("is decided by the failure code when it is benign or severe", () => {
    expect(isMinorPartial(partial({ failure_code: "page_limit_reached" }))).toBe(true);
    expect(isMinorPartial(partial({ failure_code: "remote_blocked", pages_failed: 1 }))).toBe(
      false
    );
    expect(isCompletedWithMissingResources(partial({ failure_code: "resources_missing" }))).toBe(
      true
    );
  });

  it("otherwise lets at most five percent of the items fail", () => {
    expect(isMinorPartial(partial({ pages_crawled: 95, pages_failed: 5 }))).toBe(true);
    expect(isMinorPartial(partial({ pages_crawled: 90, pages_failed: 10 }))).toBe(false);
    // Counters recorded before tracking cannot qualify.
    expect(isMinorPartial(partial({ pages_unchanged: null, pages_failed: 1 }))).toBe(false);
  });

  it("flags issues for failed items and unsuccessful end states", () => {
    expect(hasCrawlIssues(run())).toBe(false);
    expect(hasCrawlIssues(run({ files_failed: 1 }))).toBe(true);
    expect(hasCrawlIssues(run({ outcome: "interrupted" }))).toBe(true);
    expect(hasCrawlIssues(run({ outcome: "cancelled" }))).toBe(false);
  });
});

describe("failure messages", () => {
  it("picks the message for the run's failure code and outcome", () => {
    expect(crawlRunFailureMessageKey(run())).toBeNull();
    expect(crawlRunFailureMessageKey(run({ outcome: "failed", failure_code: "timed_out" }))).toBe(
      "crawl_failure_timed_out"
    );
    expect(
      crawlRunFailureMessageKey(run({ outcome: "partial", failure_code: "processing_failed" }))
    ).toBe("crawl_failure_partial");
    expect(
      crawlRunFailureMessageKey(run({ outcome: "partial", failure_code: "user_quota_exceeded" }))
    ).toBe("crawl_failure_user_quota_exceeded");
    expect(
      crawlRunFailureMessageKey(run({ outcome: "partial", failure_code: "resources_missing" }))
    ).toBe("crawl_failure_resources_missing");
  });

  it("names failure reasons however the crawler spells them, with help where there is some", () => {
    expect(crawlFailureReasonLabel(t, "EMPTY_CONTENT")).toBe("failure_reason_EMPTY_CONTENT()");
    expect(crawlFailureReasonLabel(t, "_RedirectRejected")).toBe(
      "failure_reason_redirect_rejected()"
    );
    expect(crawlFailureReasonLabel(t, "http_404")).toBe("failure_reason_not_found(status=404)");
    expect(crawlFailureReasonLabel(t, "http_503")).toBe("failure_reason_http(status=503)");
    expect(crawlFailureReasonLabel(t, "something_new")).toBe("failure_reason_other()");
    expect(crawlFailureReasonHelp(t, "http_503")).toBe("crawl_failure_help_server()");
    expect(crawlFailureReasonHelp(t, "robots_disallowed")).toBe("crawl_failure_help_robots()");
    expect(crawlFailureReasonHelp(t, "EMPTY_CONTENT")).toBeUndefined();
  });

  it("links only http(s) addresses", () => {
    expect(resourceLink("https://example.com/a b")).toBe("https://example.com/a%20b");
    expect(resourceLink("javascript:alert(1)")).toBeUndefined();
    expect(resourceLink("not a url")).toBeUndefined();
  });
});
