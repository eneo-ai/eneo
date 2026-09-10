import type { CrawlRun } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import {
  crawlRunFailureMessage,
  crawlRunState,
  crawlRunStateLabel,
  canRequestCrawlStop,
  isActiveCrawlRun,
  isCompletedWithMissingResources
} from "$lib/features/knowledge/crawlRunState";

function run(overrides: Partial<CrawlRun>): CrawlRun {
  return {
    id: crypto.randomUUID(),
    pages_crawled: null,
    files_downloaded: null,
    pages_failed: null,
    files_failed: null,
    status: "queued",
    phase: "queued",
    outcome: null,
    origin: "manual",
    result_location: null,
    finished_at: null,
    failure_code: null,
    failure_detail: null,
    cancel_requested_at: null,
    attempt_count: 1,
    ...overrides
  };
}

describe("crawlRunState", () => {
  it.each([
    ["pending_dispatch", "queued"],
    ["queued", "queued"],
    ["running", "running"],
    ["finalizing", "finalizing"],
    ["stopping", "stopping"]
  ] as const)("maps the %s phase to %s", (phase, expected) => {
    expect(crawlRunState(run({ phase }))).toBe(expected);
  });

  it.each([
    "succeeded",
    "unchanged",
    "empty",
    "partial",
    "failed",
    "cancelled",
    "interrupted"
  ] as const)("uses the terminal %s outcome", (outcome) => {
    expect(crawlRunState(run({ phase: "terminal", outcome }))).toBe(outcome);
  });

  it("does not keep polling any terminal outcome", () => {
    for (const outcome of [
      "succeeded",
      "unchanged",
      "empty",
      "partial",
      "failed",
      "cancelled",
      "interrupted"
    ] as const) {
      expect(isActiveCrawlRun(run({ phase: "terminal", outcome }))).toBe(false);
    }
    expect(isActiveCrawlRun(run({ phase: "stopping" }))).toBe(true);
  });

  it.each(["pending_dispatch", "queued", "running", "finalizing"] as const)(
    "allows a stop request while a run is %s",
    (phase) => {
      expect(canRequestCrawlStop(run({ phase }))).toBe(true);
    }
  );

  it("does not offer another stop request once stopping or terminal", () => {
    expect(canRequestCrawlStop(run({ phase: "stopping" }))).toBe(false);
    expect(canRequestCrawlStop(run({ phase: "terminal", outcome: "cancelled" }))).toBe(false);
  });

  it("surfaces an invalid terminal record instead of guessing", () => {
    expect(crawlRunState(run({ phase: "terminal", outcome: null }))).toBe("unknown");
  });

  it("uses the typed lifecycle for user-facing labels", () => {
    expect(crawlRunStateLabel(crawlRunState(run({ phase: "finalizing" })))).toBe(
      m.crawl_status_finalizing()
    );
    expect(crawlRunStateLabel(crawlRunState(run({ phase: "terminal", outcome: "empty" })))).toBe(
      m.crawl_status_empty()
    );
  });

  it("turns failure codes into actionable messages without exposing internal details", () => {
    expect(
      crawlRunFailureMessage(
        run({
          phase: "terminal",
          outcome: "interrupted",
          failure_code: "lease_expired",
          failure_detail: "redis key crawl:secret disappeared"
        })
      )
    ).toBe(m.crawl_failure_lease_expired());
  });

  it("explains partial results without describing a complete failure and preserves quota guidance", () => {
    for (const failure_code of [
      "processing_failed",
      "remote_blocked",
      "remote_unreachable",
      "timed_out"
    ] as const) {
      expect(
        crawlRunFailureMessage(run({ phase: "terminal", outcome: "partial", failure_code }))
      ).toBe(m.crawl_failure_partial());
    }
    expect(
      crawlRunFailureMessage(
        run({ phase: "terminal", outcome: "partial", failure_code: "user_quota_exceeded" })
      )
    ).toBe(m.crawl_failure_user_quota_exceeded());
    expect(
      crawlRunFailureMessage(
        run({ phase: "terminal", outcome: "partial", failure_code: "tenant_quota_exceeded" })
      )
    ).toBe(m.crawl_failure_tenant_quota_exceeded());
  });
});

it("only treats verified missing resources as a completed crawl", () => {
  const completed = run({
    phase: "terminal",
    outcome: "partial",
    failure_code: "resources_missing"
  });
  expect(isCompletedWithMissingResources(completed)).toBe(true);
  expect(crawlRunFailureMessage(completed)).toBe(m.crawl_failure_resources_missing());
  expect(crawlRunState(completed)).toBe("partial");
  expect(
    isCompletedWithMissingResources(run({ ...completed, failure_code: "processing_failed" }))
  ).toBe(false);
  expect(isCompletedWithMissingResources(run({ ...completed, outcome: "failed" }))).toBe(false);
  expect(isCompletedWithMissingResources(run({ ...completed, phase: "running" }))).toBe(false);
});
