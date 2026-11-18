import { crawlFailureMessageKey } from "@/features/knowledge/crawl-run-state";
import type { Job } from "./jobs";

type JobTask = Job["task"];
type FailureCode = NonNullable<Job["failure_code"]>;
type Translate = (key: string) => string;

const JOB_FAILURE_KEYS: Record<FailureCode, (task: JobTask) => string> = {
  extraction_failed: () => "job_failure_extraction_failed",
  no_extractable_text: (task) =>
    task === "transcription"
      ? "job_failure_no_extractable_audio"
      : "job_failure_no_extractable_text",
  encrypted: () => "job_failure_encrypted",
  corrupt: () => "job_failure_corrupt",
  unsupported_format: () => "job_failure_unsupported_format",
  processing_failed: () => "job_failure_processing_failed",
  cancelled: () => "job_failure_cancelled",
  processing_interrupted: () => "job_failure_processing_interrupted",
  invalid_job_payload: () => "job_failure_invalid_job_payload",
  quota_exceeded: () => "job_failure_quota_exceeded",
  tenant_quota_exceeded: () => "job_failure_tenant_quota_exceeded",
  user_quota_exceeded: () => "job_failure_user_quota_exceeded",
  storage_limit_exceeded: () => "job_failure_storage_limit_exceeded",
  storage_unavailable: () => "job_failure_storage_unavailable",
  storage_verification_failed: () => "job_failure_storage_verification_failed",
  knowledge_source_conflict: () => "job_failure_knowledge_source_conflict",
  dispatch_failed: () => crawlFailureMessageKey("dispatch_failed"),
  invalid_dispatch: () => crawlFailureMessageKey("invalid_dispatch"),
  worker_interrupted: () => crawlFailureMessageKey("worker_interrupted"),
  lease_expired: () => crawlFailureMessageKey("lease_expired"),
  remote_unreachable: () => crawlFailureMessageKey("remote_unreachable"),
  remote_blocked: () => crawlFailureMessageKey("remote_blocked"),
  timed_out: () => crawlFailureMessageKey("timed_out"),
  resources_missing: () => crawlFailureMessageKey("resources_missing"),
  page_limit_reached: () => crawlFailureMessageKey("page_limit_reached"),
  content_skipped: () => crawlFailureMessageKey("content_skipped")
};

// Syncs and app runs fail with the same codes; their guidance names no file.
const TASK_FAILURE_KEYS: Partial<Record<string, string>> = {
  cancelled: "job_failure_task_stopped",
  processing_interrupted: "job_failure_task_stopped",
  worker_interrupted: "job_failure_task_stopped",
  quota_exceeded: "job_failure_task_quota_exceeded",
  tenant_quota_exceeded: "job_failure_tenant_quota_exceeded",
  user_quota_exceeded: "job_failure_user_quota_exceeded",
  storage_unavailable: "job_failure_storage_unavailable"
};

/**
 * What to tell the user about a failed job: the typed failure code's
 * localized guidance, never the worker's own text. Crawls read every code
 * through the crawl guidance, uploads and transcriptions through the file
 * guidance, other tasks through guidance that names no file.
 */
export function getJobFailureMessage(
  t: Translate,
  code: string | null | undefined,
  task: JobTask
): string {
  if (task === "crawl") return t(crawlFailureMessageKey(code));
  if (task !== "upload_info_blob" && task !== "transcription") {
    return t((code && TASK_FAILURE_KEYS[code]) || "job_failure_task_failed");
  }
  const key = code
    ? (JOB_FAILURE_KEYS as Partial<Record<string, (task: JobTask) => string>>)[code]
    : undefined;
  return t(key ? key(task) : "job_failure_unknown");
}

export function isCancelledCrawl(job: Job): boolean {
  return job.task === "crawl" && job.failure_code === "cancelled";
}

/** A crawl that finished with partial results: shown as done with notes, not as failed. */
export function isCrawlWithWarnings(job: Job): boolean {
  return (
    job.task === "crawl" &&
    job.status === "complete" &&
    !!job.failure_code &&
    !isCancelledCrawl(job)
  );
}

/**
 * The message behind a job's failure row, or null when there is nothing to
 * explain (a crawl the user stopped on purpose). Uploads, transcriptions and
 * crawls are told by their typed codes. A failure of another task records
 * only its code; one recorded earlier keeps its cleaned text.
 */
export function jobFailureMessage(t: Translate, job: Job): string | null {
  if (isCancelledCrawl(job)) return null;
  if (job.task === "crawl" || job.task === "upload_info_blob" || job.task === "transcription") {
    return getJobFailureMessage(t, job.failure_code, job.task);
  }
  if (job.result_location) return job.result_location;
  return job.failure_code ? getJobFailureMessage(t, job.failure_code, job.task) : null;
}
