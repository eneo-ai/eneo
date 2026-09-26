"use client";

import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Popover } from "@astryxdesign/core/Popover";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Bell, BellDot, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { cn } from "@/lib/utils";
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

const ROW_CLASSES =
  "border-ax-border flex items-center justify-between gap-x-3 border-b px-2 py-1.5 last-of-type:border-b-0";

/**
 * File and job names wrap instead of being cut off: a `title` tooltip is not
 * reachable with the keyboard or on touch (WCAG 1.4.13, 2.1.1).
 */
const NAME_CLASSES = "min-w-0 pe-4 wrap-anywhere";

function ExpandableErrorRow({ label, message }: { label: string; message: string }) {
  const t = useTranslations();
  const [expanded, setExpanded] = useState(false);
  const messageId = useId();
  return (
    <div className="border-ax-border flex flex-col border-b px-2 py-1.5 last-of-type:border-b-0">
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        className="rounded-ax-inner focus-visible:outline-ring flex min-h-6 w-full items-center justify-between gap-x-3 text-start focus-visible:outline-2 focus-visible:outline-offset-2"
        aria-expanded={expanded}
        aria-controls={messageId}
      >
        <span className={NAME_CLASSES}>{label}</span>
        <span className="text-ax-error flex min-w-fit items-center gap-1 font-medium">
          {t("failed")}
          <ChevronDown
            aria-hidden="true"
            className={cn("size-4 transition-transform", expanded && "rotate-180")}
          />
        </span>
      </button>
      <p
        id={messageId}
        hidden={!expanded}
        className="text-ax-text-secondary py-1 text-sm break-words whitespace-normal"
      >
        {message}
      </p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="ps-1 text-sm font-medium">{title}</span>
      <div className="border-ax-border rounded-ax-container border px-3 py-1 text-sm">
        {children}
      </div>
    </div>
  );
}

function UploadRow({ upload }: { upload: Upload }) {
  const t = useTranslations();
  if (upload.status === "failed" && upload.errorMessage) {
    return <ExpandableErrorRow label={upload.file.name} message={upload.errorMessage} />;
  }
  return (
    <div className={ROW_CLASSES}>
      <span className={NAME_CLASSES}>{upload.file.name}</span>
      {upload.status === "queued" ? (
        <span className="text-ax-text-secondary min-w-fit">{t("waiting")}</span>
      ) : (
        <span className="w-40 min-w-40">
          <ProgressBar
            label={upload.file.name}
            isLabelHidden
            value={upload.progress}
            hasValueLabel
          />
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
    <div className={ROW_CLASSES}>
      <span className={NAME_CLASSES}>{label}</span>
      {isJobActive(job) ? (
        <Spinner size="sm" aria-label={t("in_progress")} />
      ) : job.status === "failed" ? (
        <span className="text-ax-error min-w-fit font-medium">{t("failed")}</span>
      ) : (
        <span className="text-ax-success min-w-fit font-medium">{t("done")}</span>
      )}
    </div>
  );
}

/**
 * The bell for uploads and background jobs, with their progress in a popover.
 * An Astryx Popover lives in the top layer next to its trigger, so it also
 * opens from inside the modal navigation drawer on phones.
 */
export function JobIndicator({ alignment = "end" }: { alignment?: "start" | "end" }) {
  const t = useTranslations();
  const { jobs, uploads, runningCount } = useJobs();

  const sections = TASK_SECTIONS.map(([task, titleKey]) => ({
    titleKey,
    jobs: jobs.filter((job) => job.task === task)
  })).filter((section) => section.jobs.length > 0);
  const label =
    runningCount > 0 ? t("fix_notifications_running", { count: runningCount }) : t("notifications");

  return (
    <Popover
      label={t("notifications_and_jobs")}
      placement="below"
      alignment={alignment}
      width={384}
      content={
        <div className="flex flex-col gap-3">
          <p className="text-ax-text-secondary font-mono text-sm font-medium">
            {t("notifications_and_jobs")}
          </p>
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
            <p className="text-ax-text-secondary flex min-h-24 items-center justify-center text-sm">
              {t("everything_up_to_date")}
            </p>
          )}
        </div>
      }
    >
      <IconButton
        variant="ghost"
        label={label}
        tooltip={label}
        icon={
          <Icon
            icon={runningCount === 0 ? Bell : BellDot}
            color={runningCount === 0 ? "inherit" : "accent"}
          />
        }
      />
    </Popover>
  );
}
