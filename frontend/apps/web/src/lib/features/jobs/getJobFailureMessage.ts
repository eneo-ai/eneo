import type { Job, JobFailureCode } from "@eneo/eneo-js";
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
  invalid_job_payload: () => m.job_failure_invalid_job_payload()
};

export function getJobFailureMessage(
  code: JobFailureCode | string | null | undefined,
  task: JobTask
): string {
  const message = code
    ? (JOB_FAILURE_MESSAGES as Partial<Record<string, (task: JobTask) => string>>)[code]
    : undefined;
  return message ? message(task) : m.job_failure_unknown();
}
