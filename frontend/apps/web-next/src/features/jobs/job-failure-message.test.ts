import { describe, expect, it } from "vitest";
import {
  getJobFailureMessage,
  isCrawlWithWarnings,
  jobFailureMessage
} from "./job-failure-message";
import type { Job } from "./use-jobs";

const t = (key: string) => key;
const job = (overrides: Partial<Job>): Job =>
  ({ id: "job-1", name: "intranet.example", task: "crawl", status: "failed", ...overrides }) as Job;

describe("getJobFailureMessage", () => {
  it("reuses crawl recovery guidance for typed crawl failures", () => {
    expect(getJobFailureMessage(t, "remote_unreachable", "crawl")).toBe(
      "crawl_failure_remote_unreachable"
    );
  });

  it.each(["tenant_quota_exceeded", "user_quota_exceeded"])(
    "identifies which storage quota stopped a crawl: %s",
    (code) => {
      expect(getJobFailureMessage(t, code, "crawl")).toBe(`crawl_failure_${code}`);
      expect(getJobFailureMessage(t, code, "upload_info_blob")).toBe(`crawl_failure_${code}`);
    }
  );

  it("uses the safe localized fallback instead of worker details", () => {
    for (const code of [null, undefined, "future_failure_code"]) {
      expect(getJobFailureMessage(t, code, "crawl")).toBe("crawl_failure_unknown");
      expect(getJobFailureMessage(t, code, "upload_info_blob")).toBe("job_failure_unknown");
    }
    expect(getJobFailureMessage(t, "timed_out", "crawl")).toBe("crawl_failure_timed_out");
  });

  it("tells transcriptions and uploads apart for missing content", () => {
    expect(getJobFailureMessage(t, "no_extractable_text", "transcription")).toBe(
      "job_failure_no_extractable_audio"
    );
    expect(getJobFailureMessage(t, "no_extractable_text", "upload_info_blob")).toBe(
      "job_failure_no_extractable_text"
    );
  });
});

describe("jobFailureMessage", () => {
  it("has nothing to explain for a crawl the user stopped", () => {
    expect(jobFailureMessage(t, job({ failure_code: "cancelled" }))).toBeNull();
  });

  it("keeps the recorded result text for tasks without typed codes", () => {
    expect(
      jobFailureMessage(t, job({ task: "run_app", result_location: "Appen svarade inte" }))
    ).toBe("Appen svarade inte");
  });

  it("marks a crawl that completed with notes as a warning, not a failure", () => {
    expect(
      isCrawlWithWarnings(job({ status: "complete", failure_code: "page_limit_reached" }))
    ).toBe(true);
    expect(isCrawlWithWarnings(job({ status: "complete", failure_code: "cancelled" }))).toBe(false);
    expect(isCrawlWithWarnings(job({ status: "complete" }))).toBe(false);
    expect(isCrawlWithWarnings(job({ status: "failed", failure_code: "timed_out" }))).toBe(false);
  });
});
