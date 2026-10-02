import type { Schema } from "@/lib/api/models";
import { isCancelledCrawl } from "./job-failure-message";

/** A background job as the backend reports it (uploads, crawls, app runs…). */
export type Job = Schema<"JobPublic">;

/** The query key of the signed-in user's job list; polled by JobsProvider. */
export const JOBS_KEY = ["jobs"] as const;

/** Still queued or running: the bell shows a spinner and polling stays fast. */
export function isJobActive(job: Job): boolean {
  return job.status === "in progress" || job.status === "queued";
}

/** How a job ended, from the user's point of view. */
export type JobOutcome = "completed" | "failed" | "cancelled";

/** The outcome of a job that is no longer active, or null while it still runs. */
export function jobOutcome(job: Job): JobOutcome | null {
  if (isJobActive(job)) return null;
  if (isCancelledCrawl(job)) return "cancelled";
  return job.status === "failed" ? "failed" : "completed";
}

const INFO_BLOB_RESULT = /^\/api\/v1\/info-blobs\/([0-9a-f-]{36})\/?$/i;

/**
 * The info-blob an upload job produced, read from the job's result location
 * (`/api/v1/info-blobs/{id}/`, set by the upload worker). Lets the file's row
 * be pointed out when it appears. Null for every other kind of result.
 */
export function jobResultInfoBlobId(job: Job): string | null {
  const match = job.result_location ? INFO_BLOB_RESULT.exec(job.result_location) : null;
  return match?.[1] ?? null;
}
