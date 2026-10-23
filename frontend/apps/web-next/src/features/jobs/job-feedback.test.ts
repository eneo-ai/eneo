import { describe, expect, it } from "vitest";
import { describeJobOutcome } from "./job-feedback";
import type { Job } from "./jobs";

const t = (key: string, values?: Record<string, string | number>) =>
  `${key}${values ? ":" + Object.values(values).join(",") : ""}`;
const job = (extra: Partial<Job>): Job => ({ id: "j", name: "Avtal.pdf", ...extra }) as Job;

describe("describeJobOutcome", () => {
  it("says an uploaded file is searchable, other jobs are done", () => {
    expect(describeJobOutcome(job({ task: "upload_info_blob" }), "completed", t)).toEqual({
      tone: "success",
      title: "job_toast_upload_ready:Avtal.pdf"
    });
    expect(describeJobOutcome(job({ task: "crawl" }), "completed", t)).toEqual({
      tone: "success",
      title: "job_toast_completed:Avtal.pdf"
    });
  });

  it("carries the failure reason as the description", () => {
    const feedback = describeJobOutcome(
      job({ task: "upload_info_blob", status: "failed", failure_code: "encrypted" }),
      "failed",
      t
    );
    expect(feedback.tone).toBe("error");
    expect(feedback.title).toBe("job_toast_failed:Avtal.pdf");
    expect(feedback.description).toBeTruthy();
  });

  it("treats a stopped crawl as information, not an error", () => {
    expect(describeJobOutcome(job({ task: "crawl" }), "cancelled", t)).toEqual({
      tone: "info",
      title: "job_toast_cancelled:Avtal.pdf"
    });
  });

  it("falls back to the id when the job has no name", () => {
    expect(describeJobOutcome(job({ name: null, task: "crawl" }), "completed", t).title).toBe(
      "job_toast_completed:j"
    );
  });
});
