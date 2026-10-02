"use client";

import { useTranslations } from "next-intl";
import { useId } from "react";
import { useClientTimeText } from "@/components/composites/client-time";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import type { CrawlerSchedulerHealth } from "./crawler";

const STATUS: Record<
  CrawlerSchedulerHealth["status"],
  { tone: StatusTone; labelKey: string; helpKey?: string }
> = {
  ok: { tone: "success", labelKey: "admin_crawler_scheduler_ok" },
  degraded: {
    tone: "warning",
    labelKey: "admin_crawler_scheduler_degraded",
    helpKey: "admin_crawler_scheduler_help_degraded"
  },
  stale: {
    tone: "error",
    labelKey: "admin_crawler_scheduler_stale",
    helpKey: "admin_crawler_scheduler_help_stale"
  },
  unknown: {
    tone: "neutral",
    labelKey: "admin_crawler_scheduler_unknown",
    helpKey: "admin_crawler_scheduler_help_unknown"
  }
};

/**
 * Whether the hourly scheduler ran recently and admitted every due website:
 * its state, when it last ran and what it did, with what to do when it is
 * not fine. The time shows after hydration (ClientTime).
 */
export function SchedulerHealth({ scheduler }: { scheduler: CrawlerSchedulerHealth }) {
  const t = useTranslations();
  const headingId = useId();
  const status = STATUS[scheduler.status];
  const lastRun = useClientTimeText(scheduler.ran_at, "date_time");
  const hasCounts = scheduler.due != null && scheduler.admitted != null && scheduler.failed != null;

  return (
    <div role="group" aria-labelledby={headingId} className="flex flex-col gap-1 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span id={headingId}>{t("admin_crawler_scheduler")}</span>
        <StatusLabel status={status.tone} label={t(status.labelKey)} />
        {scheduler.status !== "unknown" ? (
          <>
            <span className="text-ax-text-secondary">
              {t("admin_crawler_scheduler_last_run", { time: lastRun ?? "—" })}
            </span>
            {hasCounts ? (
              <span className="text-ax-text-secondary tabular-nums">
                {t("admin_crawler_scheduler_counts", {
                  due: scheduler.due ?? 0,
                  admitted: scheduler.admitted ?? 0,
                  failed: scheduler.failed ?? 0
                })}
              </span>
            ) : null}
          </>
        ) : null}
      </div>
      {status.helpKey ? (
        <p className="text-ax-text-secondary max-w-3xl text-xs leading-5">{t(status.helpKey)}</p>
      ) : null}
    </div>
  );
}
