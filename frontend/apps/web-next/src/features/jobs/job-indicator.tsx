"use client";

import { Bell, BellDot, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { isJobActive, useJobs, type Job, type Upload } from "./use-jobs";

/** Job task → i18n key for the panel section heading. */
const TASK_SECTIONS: [Job["task"], string][] = [
  ["upload_info_blob", "analysing"],
  ["embed_group", "embedding"],
  ["transcription", "transcribing"],
  ["pull_confluence_content", "importing_from_confluence"],
  ["pull_sharepoint_content", "importing_from_sharepoint"],
  ["crawl", "crawling"]
];

function ExpandableErrorRow({ label, message }: { label: string; message: string }) {
  const [expanded, setExpanded] = useState(false);
  const t = useTranslations();
  return (
    <div className="border-border flex flex-col border-b px-2 py-1.5 last-of-type:border-b-0">
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        className="flex w-full items-center justify-between gap-x-3 text-left"
        aria-expanded={expanded}
      >
        <span className="truncate pr-4" title={label}>
          {label}
        </span>
        <span className="text-destructive flex min-w-fit items-center gap-1 font-medium">
          {t("failed")}
          <ChevronDown className={`size-4 transition-transform ${expanded ? "rotate-180" : ""}`} />
        </span>
      </button>
      {expanded && (
        <p className="text-muted-foreground py-1 text-sm break-words whitespace-normal">
          {message}
        </p>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 px-2 py-2">
      <span className="pl-1 text-sm font-medium">{title}</span>
      <div className="rounded-lg border px-3 py-1 text-sm shadow-sm">{children}</div>
    </div>
  );
}

function UploadRow({ upload }: { upload: Upload }) {
  const t = useTranslations();
  if (upload.status === "failed" && upload.errorMessage) {
    return <ExpandableErrorRow label={upload.file.name} message={upload.errorMessage} />;
  }
  return (
    <div className="border-border flex items-center justify-between gap-x-3 border-b px-2 py-1.5 whitespace-nowrap last-of-type:border-b-0">
      <span className="truncate pr-4" title={upload.file.name}>
        {upload.file.name}
      </span>
      {upload.status === "queued" ? (
        <span className="text-muted-foreground min-w-fit">{t("waiting")}</span>
      ) : (
        <span className="flex w-40 min-w-40 items-center gap-x-3">
          <Progress value={upload.progress} />
          <span className="w-10 text-end text-sm">{upload.progress}%</span>
        </span>
      )}
    </div>
  );
}

function JobRow({ job }: { job: Job }) {
  const t = useTranslations();
  const label = job.name ?? job.id;
  if (job.status === "failed" && job.result_location) {
    return <ExpandableErrorRow label={label} message={job.result_location} />;
  }
  return (
    <div className="border-border flex items-center justify-between gap-x-3 border-b px-2 py-1.5 whitespace-nowrap last-of-type:border-b-0">
      <span className="truncate pr-4" title={label}>
        {label}
      </span>
      {isJobActive(job) ? (
        <Spinner className="size-4" />
      ) : job.status === "failed" ? (
        <span className="text-destructive min-w-fit font-medium">{t("failed")}</span>
      ) : (
        <span className="min-w-fit font-medium text-green-600 dark:text-green-500">
          {t("done")}
        </span>
      )}
    </div>
  );
}

export function JobIndicator() {
  const t = useTranslations();
  const { jobs, uploads, runningCount } = useJobs();

  const sections = TASK_SECTIONS.map(([task, titleKey]) => ({
    titleKey,
    jobs: jobs.filter((job) => job.task === task)
  })).filter((section) => section.jobs.length > 0);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={t("notifications")}>
          {runningCount === 0 ? (
            <Bell className="size-5" />
          ) : (
            <BellDot className="text-primary size-5" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="flex max-h-[70vh] w-96 flex-col overflow-y-auto p-0">
        <p className="text-muted-foreground border-b px-4 pt-2 pb-2.5 font-mono text-sm font-medium">
          {t("notifications_and_jobs")}
        </p>
        <div className="p-2">
          {uploads.length > 0 && (
            <Section title={t("uploading")}>
              {uploads.map((upload) => (
                <UploadRow key={upload.id} upload={upload} />
              ))}
            </Section>
          )}
          {sections.map((section) => (
            <Section key={section.titleKey} title={t(section.titleKey)}>
              {section.jobs.map((job) => (
                <JobRow key={job.id} job={job} />
              ))}
            </Section>
          ))}
          {runningCount === 0 && sections.length === 0 && uploads.length === 0 && (
            <div className="text-muted-foreground flex h-24 w-full items-center justify-center text-sm">
              {t("everything_up_to_date")}
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
