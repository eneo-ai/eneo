import { expect, test } from "vitest";
import type { Job } from "@intric/intric-js";
import { getJobResultDetail } from "./jobResultPresentation";

test("crawl jobs do not expose raw result_location in the generic job dropdown", () => {
  const job = {
    task: "crawl",
    result_location: "legacy raw crawler result"
  } as unknown as Job;

  expect(getJobResultDetail(job)).toBeUndefined();
});

test("non-crawl jobs keep their result detail", () => {
  const job = {
    task: "upload_info_blob",
    result_location: "File analysis completed"
  } as unknown as Job;

  expect(getJobResultDetail(job)).toBe("File analysis completed");
});

test("blank result details are hidden", () => {
  const job = {
    task: "upload_info_blob",
    result_location: "   "
  } as unknown as Job;

  expect(getJobResultDetail(job)).toBeUndefined();
});
