import type { Job } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import JobListView from "./JobListView.svelte";

function failedJob(overrides: Partial<Job>): Job {
  return {
    id: crypto.randomUUID(),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    name: "document.pdf",
    status: "failed",
    task: "upload_info_blob",
    result_location: null,
    failure_code: null,
    finished_at: new Date().toISOString(),
    ...overrides
  } as Job;
}

describe("JobListView failure presentation", () => {
  it("shows the localized typed reason for a failed knowledge job", async () => {
    render(JobListView, {
      jobs: [failedJob({ failure_code: "encrypted" })],
      title: "Knowledge"
    });

    await page.getByRole("button", { name: /document\.pdf/ }).click();

    await expect.element(page.getByText(m.job_failure_encrypted(), { exact: true })).toBeVisible();
  });

  it("hides legacy knowledge exception prose behind the safe localized fallback", async () => {
    render(JobListView, {
      jobs: [failedJob({ result_location: "password=secret database host" })],
      title: "Knowledge"
    });

    await page.getByRole("button", { name: /document\.pdf/ }).click();

    await expect.element(page.getByText(m.job_failure_unknown(), { exact: true })).toBeVisible();
    await expect
      .element(page.getByText("password=secret database host", { exact: true }))
      .not.toBeInTheDocument();
  });

  it("shows transcription guidance when no speech can be extracted", async () => {
    render(JobListView, {
      jobs: [
        failedJob({
          name: "meeting.mp3",
          task: "transcription",
          failure_code: "no_extractable_text"
        })
      ],
      title: "Transcriptions"
    });

    await page.getByRole("button", { name: /meeting\.mp3/ }).click();

    await expect
      .element(page.getByText(m.job_failure_no_extractable_audio(), { exact: true }))
      .toBeVisible();
  });

  it("preserves non-knowledge result details used by crawl jobs", async () => {
    render(JobListView, {
      jobs: [
        failedJob({
          name: "intranet.example",
          task: "crawl",
          result_location: "The crawl exceeded its configured time limit"
        })
      ],
      title: "Crawls"
    });

    await page.getByRole("button", { name: /intranet\.example/ }).click();

    await expect
      .element(page.getByText("The crawl exceeded its configured time limit", { exact: true }))
      .toBeVisible();
  });
});
