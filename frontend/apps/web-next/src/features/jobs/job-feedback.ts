import { jobFailureMessage } from "./job-failure-message";
import type { Job, JobOutcome } from "./jobs";

type Translate = (key: string, values?: Record<string, string | number>) => string;

export type JobFeedback = {
  tone: "success" | "error" | "info";
  /** One sentence naming the job and what happened. */
  title: string;
  /** The failure reason, when the backend gave one. */
  description?: string;
};

/**
 * The words for a job that just ended: shown as a toast and announced to
 * screen readers. Uploads say the file is searchable, since the earlier
 * "uploaded" toast only meant the bytes had arrived.
 */
export function describeJobOutcome(job: Job, outcome: JobOutcome, t: Translate): JobFeedback {
  const name = job.name ?? job.id;
  if (outcome === "completed") {
    return {
      tone: "success",
      title:
        job.task === "upload_info_blob"
          ? t("job_toast_upload_ready", { name })
          : t("job_toast_completed", { name })
    };
  }
  if (outcome === "cancelled") {
    return { tone: "info", title: t("job_toast_cancelled", { name }) };
  }
  return {
    tone: "error",
    title: t("job_toast_failed", { name }),
    description: jobFailureMessage(t, job) ?? undefined
  };
}
