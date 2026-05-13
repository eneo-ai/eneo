import { expect, test } from "vitest";
import type { CrawlRun, WebsiteSparse } from "@intric/intric-js";
import { overwriteGetLocale } from "$lib/paraglide/runtime";
import {
  getCrawlOutcome,
  getCrawlOutcomeLabel,
  getCrawlOutcomeTooltip,
  getCrawlRunFailureDetail,
  getCrawlRunCountBreakdown,
  getCrawlRunResultLabels,
  getFailureSummaryTooltip,
  getLatestCrawlOutcome,
  getPagesSourceRetained,
  getSourceRetainedLabel,
  isDuplicateCrawlSkip,
  isSourceRetentionOnly,
  type CrawlOutcome
} from "./crawlOutcomePresentation";

overwriteGetLocale(() => "en");

const sourceRetentionOutcome: CrawlOutcome = {
  code: "CRAWL_SOURCE_RETENTION_ONLY",
  severity: "info",
  message_key: "crawl_outcome_source_retention_only"
};

test("source retention outcome uses the localized label", () => {
  expect(getCrawlOutcomeLabel(sourceRetentionOutcome, "fallback")).toBe(
    "No page downloads were needed"
  );
  expect(isSourceRetentionOnly(sourceRetentionOutcome)).toBe(true);
});

test("outcome tooltip includes affected count and detail", () => {
  expect(
    getCrawlOutcomeTooltip(
      {
        code: "CRAWL_COMPLETED_WITH_PAGE_FAILURES",
        severity: "warning",
        message_key: "crawl_outcome_page_failures",
        affected_count: 3,
        detail: "Three pages failed during embedding"
      },
      "fallback"
    )
  ).toBe("Completed with page or file failures\n3 affected\nThree pages failed during embedding");
});

test("partial timeout outcome has a localized label", () => {
  expect(
    getCrawlOutcomeLabel(
      {
        code: "CRAWL_PARTIAL_TIMEOUT",
        severity: "warning",
        message_key: "crawl_outcome_partial_timeout"
      },
      "fallback"
    )
  ).toBe("Partially completed");
});

test("shutdown outcome has a localized label", () => {
  expect(
    getCrawlOutcomeLabel(
      {
        code: "CRAWL_SHUTDOWN_ERROR",
        severity: "error",
        message_key: "crawl_outcome_shutdown_error"
      },
      "fallback"
    )
  ).toBe("Crawler shutdown failed");
});

test("unknown outcome message key falls back to detail", () => {
  expect(
    getCrawlOutcomeLabel(
      {
        code: "CRAWL_FUTURE_CODE",
        severity: "error",
        message_key: "crawl_outcome_future_code",
        detail: "Future crawl outcome"
      },
      "fallback"
    )
  ).toBe("Future crawl outcome");
});

test("failed crawl exposes stored diagnostic detail", () => {
  const outcome: CrawlOutcome = {
    code: "UNKNOWN_CRAWL_ERROR",
    severity: "error",
    message_key: "crawl_outcome_unknown_error",
    detail: "Crawler stopped before collecting pages"
  };
  const crawl = {
    status: "failed",
    result_location: "Preempted: Job was stale",
    outcome
  } as unknown as CrawlRun;

  expect(getCrawlOutcomeLabel(outcome, "fallback")).toBe("Crawl failed");
  expect(getCrawlRunFailureDetail(crawl)).toBe("Crawler stopped before collecting pages");
});

test("failed crawl without stored detail explains the diagnostic gap", () => {
  const crawl = {
    status: "failed",
    result_location: null,
    outcome: {
      code: "UNKNOWN_CRAWL_ERROR",
      severity: "error",
      message_key: "crawl_outcome_unknown_error"
    }
  } as unknown as CrawlRun;

  expect(getCrawlRunFailureDetail(crawl)).toBe(
    "No technical error detail was stored for this crawl run."
  );
});

test("missing outcome has no tooltip", () => {
  expect(getCrawlOutcomeTooltip(undefined, "fallback")).toBeUndefined();
});

test("outcome access is centralized while generated crawl types catch up", () => {
  const crawl = {
    outcome: {
      code: "CRAWL_DUPLICATE_SKIPPED",
      severity: "info",
      message_key: "crawl_outcome_duplicate_skipped"
    }
  } as unknown as CrawlRun;

  const outcome = getCrawlOutcome(crawl);

  expect(outcome?.code).toBe("CRAWL_DUPLICATE_SKIPPED");
  expect(isDuplicateCrawlSkip(outcome)).toBe(true);
});

test("latest crawl outcome access is centralized while generated website types catch up", () => {
  const website = {
    latest_crawl: {
      outcome: sourceRetentionOutcome
    }
  };

  expect(getLatestCrawlOutcome(website as unknown as WebsiteSparse)).toEqual(
    sourceRetentionOutcome
  );
});

test("failure summary tooltip renders known failure reasons", () => {
  expect(getFailureSummaryTooltip({ NO_EMBEDDING_MODEL: 2 })).toBe(
    "Failure breakdown:\nNo embedding model: 2"
  );
});

test("source-retained count is absent for historical rows", () => {
  const crawl = { pages_source_retained: null } as unknown as CrawlRun;

  expect(getPagesSourceRetained(crawl)).toBeUndefined();
});

test("source-retained count is exposed for mixed source-skip crawls", () => {
  const crawl = { pages_source_retained: 100 } as unknown as CrawlRun;

  expect(getPagesSourceRetained(crawl)).toBe(100);
  expect(getSourceRetainedLabel(100)).toBe("Retained 100 unchanged pages");
});

test("crawl run count breakdown uses backend processing summary when present", () => {
  const crawl = {
    pages_crawled: 999,
    files_downloaded: 999,
    pages_failed: 0,
    files_failed: 0,
    processing_summary: {
      pages_fetched: 300,
      files_downloaded: 4,
      pages_indexed: 10,
      files_indexed: 2,
      pages_hash_retained: 290,
      files_hash_retained: 1,
      files_too_large_skipped: 2,
      pages_source_retained: 12,
      pages_failed: 0,
      files_failed: 1
    }
  } as unknown as CrawlRun;

  expect(getCrawlRunCountBreakdown(crawl)).toEqual({
    pages_fetched: 300,
    files_downloaded: 4,
    pages_indexed: 10,
    files_indexed: 2,
    pages_hash_retained: 290,
    files_hash_retained: 1,
    files_too_large_skipped: 2,
    pages_source_retained: 12,
    pages_failed: 0,
    files_failed: 1
  });
});

test("crawl run result labels distinguish fetched indexed and unchanged content", () => {
  const crawl = {
    status: "complete",
    processing_summary: {
      pages_fetched: 300,
      files_downloaded: 1,
      pages_indexed: 10,
      files_indexed: 0,
      pages_hash_retained: 290,
      files_hash_retained: 1,
      files_too_large_skipped: 0,
      pages_source_retained: 0,
      pages_failed: 0,
      files_failed: 0
    }
  } as unknown as CrawlRun;

  expect(getCrawlRunResultLabels(crawl).map((item) => item.label)).toEqual([
    "Fetched 300 pages and 1 file",
    "Indexed 10 pages",
    "Unchanged: 290 pages and 1 file"
  ]);
});

test("all unchanged crawl run labels do not claim content was indexed", () => {
  const crawl = {
    status: "complete",
    outcome: {
      code: "CRAWL_ALL_UNCHANGED",
      severity: "info",
      message_key: "crawl_outcome_all_unchanged",
      affected_count: 4
    },
    processing_summary: {
      pages_fetched: 3,
      files_downloaded: 1,
      pages_indexed: 0,
      files_indexed: 0,
      pages_hash_retained: 3,
      files_hash_retained: 1,
      files_too_large_skipped: 0,
      pages_source_retained: 0,
      pages_failed: 0,
      files_failed: 0
    }
  } as unknown as CrawlRun;

  expect(getCrawlRunResultLabels(crawl).map((item) => item.label)).toEqual([
    "Fetched 3 pages and 1 file",
    "Unchanged: 3 pages and 1 file"
  ]);
  expect(getCrawlRunResultLabels(crawl)[1].tooltip).toBe("All content was unchanged\n4 affected");
});

test("crawl run labels explain files skipped by size limit", () => {
  const crawl = {
    status: "complete",
    processing_summary: {
      pages_fetched: 3,
      files_downloaded: 1,
      pages_indexed: 3,
      files_indexed: 1,
      pages_hash_retained: 0,
      files_hash_retained: 0,
      files_too_large_skipped: 12,
      pages_source_retained: 0,
      pages_failed: 0,
      files_failed: 0
    }
  } as unknown as CrawlRun;

  const labels = getCrawlRunResultLabels(crawl);

  expect(labels.map((item) => item.label)).toEqual([
    "Fetched 3 pages and 1 file",
    "Indexed 3 pages and 1 file",
    "Too large: 12 files"
  ]);
  expect(labels[2].tooltip).toBe(
    "12 files were skipped because they exceed the crawler download size limit."
  );
});
