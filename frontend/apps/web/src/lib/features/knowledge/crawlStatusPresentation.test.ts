import { expect, test } from "vitest";
import type { CrawlRun } from "@intric/intric-js";
import { overwriteGetLocale } from "$lib/paraglide/runtime";
import { getCrawlRunStatus } from "./crawlStatusPresentation";

overwriteGetLocale(() => "en");

test("failed status does not expose raw legacy result_location when outcome detail is missing", () => {
  const crawl = {
    status: "failed",
    result_location: "legacy raw result detail",
    outcome: null
  } as unknown as CrawlRun;

  expect(getCrawlRunStatus(crawl).tooltip).toBe(
    "No technical error detail was stored for this crawl run."
  );
});

test("not found status does not expose raw legacy result_location when outcome detail is missing", () => {
  const crawl = {
    status: "not found",
    result_location: "legacy raw result detail",
    outcome: null
  } as unknown as CrawlRun;

  expect(getCrawlRunStatus(crawl).tooltip).toBe(
    "No technical error detail was stored for this crawl run."
  );
});

test("failed status uses typed outcome detail when present", () => {
  const crawl = {
    status: "failed",
    result_location: "legacy raw result detail",
    outcome: {
      code: "CRAWL_RUNTIME_TIMEOUT",
      severity: "error",
      message_key: "crawl_outcome_runtime_timeout",
      detail: "Crawl exceeded the maximum runtime of 12 hours and was stopped"
    }
  } as unknown as CrawlRun;

  expect(getCrawlRunStatus(crawl).tooltip).toBe(
    "The crawl ran too long and was stopped\n" +
      "Crawl exceeded the maximum runtime of 12 hours and was stopped"
  );
});
