import type { Job } from "@intric/intric-js";

export function getJobResultDetail(job: Job): string | undefined {
  if (job.task === "crawl") {
    return undefined;
  }

  const detail = job.result_location?.trim();
  return detail ? detail : undefined;
}
