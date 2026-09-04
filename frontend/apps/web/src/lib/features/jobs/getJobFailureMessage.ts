import type { Job, JobFailureCode } from "@eneo/eneo-js";
import { crawlFailureMessage } from "$lib/features/knowledge/crawlRunState";
import { m } from "$lib/paraglide/messages";

type JobTask = Job["task"];

const JOB_FAILURE_MESSAGES: Record<JobFailureCode, (task: JobTask) => string> = {
  extraction_failed: () => m.job_failure_extraction_failed(),
  no_extractable_text: (task) =>
    task === "transcription"
      ? m.job_failure_no_extractable_audio()
      : m.job_failure_no_extractable_text(),
  encrypted: () => m.job_failure_encrypted(),
  corrupt: () => m.job_failure_corrupt(),
  unsupported_format: () => m.job_failure_unsupported_format(),
  processing_failed: () => m.job_failure_processing_failed(),
  cancelled: () => m.job_failure_cancelled(),
  processing_interrupted: () => m.job_failure_processing_interrupted(),
  invalid_job_payload: () => m.job_failure_invalid_job_payload(),
  quota_exceeded: () => m.job_failure_quota_exceeded(),
  storage_limit_exceeded: () => m.job_failure_storage_limit_exceeded(),
  storage_unavailable: () => m.job_failure_storage_unavailable(),
  storage_verification_failed: () => m.job_failure_storage_verification_failed(),
  knowledge_source_conflict: () => m.job_failure_knowledge_source_conflict(),
  dispatch_failed: () => crawlFailureMessage("dispatch_failed"),
  invalid_dispatch: () => crawlFailureMessage("invalid_dispatch"),
  worker_interrupted: () => crawlFailureMessage("worker_interrupted"),
  lease_expired: () => crawlFailureMessage("lease_expired"),
  remote_unreachable: () => crawlFailureMessage("remote_unreachable"),
  remote_blocked: () => crawlFailureMessage("remote_blocked"),
  timed_out: () => crawlFailureMessage("timed_out")
};

export function getJobFailureMessage(
  code: JobFailureCode | string | null | undefined,
  task: JobTask
): string {
  if (task === "crawl") return crawlFailureMessage(code);

  const message = code
    ? (JOB_FAILURE_MESSAGES as Partial<Record<string, (task: JobTask) => string>>)[code]
    : undefined;
  return message ? message(task) : m.job_failure_unknown();
}
