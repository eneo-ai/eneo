import { expect, test } from "vitest";
import type { CrawlRun, WebsiteSparse } from "@intric/intric-js";
import { overwriteGetLocale } from "$lib/paraglide/runtime";
import {
  getCrawlOutcome,
  getCrawlOutcomeLabel,
  getCrawlOutcomeTooltip,
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
