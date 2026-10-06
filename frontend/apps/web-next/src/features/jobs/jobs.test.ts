import { describe, expect, it } from "vitest";
import { jobOutcome, jobResultInfoBlobId, type Job } from "./jobs";

const job = (overrides: Partial<Job>): Job =>
  ({ id: "j", task: "upload_info_blob", status: "complete", ...overrides }) as Job;

describe("jobOutcome", () => {
  it("is null while the job is queued or running", () => {
    expect(jobOutcome(job({ status: "queued" }))).toBeNull();
    expect(jobOutcome(job({ status: "in progress" }))).toBeNull();
  });

  it("tells completed, failed and a stopped crawl apart", () => {
    expect(jobOutcome(job({ status: "complete" }))).toBe("completed");
    expect(jobOutcome(job({ status: "failed" }))).toBe("failed");
    expect(jobOutcome(job({ task: "crawl", status: "failed", failure_code: "cancelled" }))).toBe(
      "cancelled"
    );
  });
});

describe("jobResultInfoBlobId", () => {
  it("reads the info-blob an upload produced from its result location", () => {
    expect(
      jobResultInfoBlobId(
        job({ result_location: "/api/v1/info-blobs/5d1b9c1e-0b4e-4c21-9d7c-2f0f0a6d3e11/" })
      )
    ).toBe("5d1b9c1e-0b4e-4c21-9d7c-2f0f0a6d3e11");
  });

  it("ignores every other result", () => {
    expect(
      jobResultInfoBlobId(job({ result_location: "/api/v1/websites/x/info-blobs/" }))
    ).toBeNull();
    expect(jobResultInfoBlobId(job({ result_location: null }))).toBeNull();
  });
});
