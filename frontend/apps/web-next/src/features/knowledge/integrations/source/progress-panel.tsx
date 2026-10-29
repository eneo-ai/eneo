"use client";

import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { Check, Loader2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId } from "react";
import { useClientTimeText } from "@/components/composites/client-time";
import { useProgressText } from "../source-status";
import { SYNC_PHASES, type SyncProgressPhase, type SyncProgressSummary } from "../sync-progress";

const PHASE_LABEL: Record<SyncProgressPhase, string> = {
  discovering: "integration_progress_phase_discovering",
  processing: "integration_progress_phase_processing",
  finishing: "integration_progress_phase_finishing"
};

/** The file a syncing folder reads right now, for a source of several folders. */
export type NowReading = { folder: string; file: string };

/**
 * A source's running sync: how far it is, the three steps of a sync and, on a
 * source of many folders, the file each syncing folder reads right now.
 */
export function SyncProgressPanel({
  progress,
  sourceName,
  firstSync,
  nowReading = []
}: {
  progress: SyncProgressSummary;
  sourceName: string;
  /** No item of the source has finished a sync before. */
  firstSync: boolean;
  nowReading?: NowReading[];
}) {
  const t = useTranslations();
  const headingId = useId();
  const progressText = useProgressText();
  const started = useClientTimeText(progress.startedAt, "date_time");
  const currentPhase = SYNC_PHASES.indexOf(progress.phase);
  const readable = progress.indexed + progress.unchanged;
  const known = progress.total !== null && progress.total > 0;
  const remaining = progress.total === null ? null : Math.max(0, progress.total - progress.done);

  return (
    <section
      aria-labelledby={headingId}
      className="border-ax-border-strong bg-ax-card rounded-ax-container flex flex-col gap-4 border p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-center gap-2">
          <Loader2
            className="text-ax-text-accent size-4 shrink-0 motion-safe:animate-spin"
            aria-hidden="true"
          />
          <h2 id={headingId} className="text-base font-semibold">
            {firstSync
              ? t("integration_progress_first_sync")
              : t("integration_progress_sync_running")}
          </h2>
        </div>
        <span className="text-ax-text-secondary text-sm">
          {started ? t("integration_progress_started", { time: started }) : null}
          {progress.syncing > 1
            ? ` · ${t("integration_progress_folders_syncing", { count: progress.syncing })}`
            : null}
        </span>
      </div>

      <div className="flex flex-col gap-2">
        <ProgressBar
          label={t("integration_progress_label", { name: sourceName })}
          isLabelHidden
          isIndeterminate={!known}
          value={known ? Math.min(progress.done, progress.total ?? 0) : 0}
          max={known ? (progress.total ?? 1) : 100}
        />
        <p className="text-sm font-medium tabular-nums">{progressText(progress)}</p>
        <ul className="text-ax-text-secondary flex flex-wrap gap-x-5 gap-y-1 text-sm">
          <li>{t("integration_progress_readable", { count: readable })}</li>
          {progress.skipped > 0 ? (
            <li className="text-ax-warning">
              {t("integration_progress_skipped", { count: progress.skipped })}
            </li>
          ) : null}
          {remaining !== null ? (
            <li>{t("integration_progress_remaining", { count: remaining })}</li>
          ) : null}
        </ul>
      </div>

      <ol className="grid gap-2 sm:grid-cols-3" aria-label={t("integration_progress_steps")}>
        {SYNC_PHASES.map((phase, index) => {
          const done = index < currentPhase;
          const active = index === currentPhase;
          return (
            <li
              key={phase}
              aria-current={active ? "step" : undefined}
              className={`bg-ax-surface rounded-ax-element flex items-center gap-2 border px-3 py-2 text-sm ${
                active ? "border-ax-border-strong font-medium" : "border-ax-border"
              } ${done || active ? "" : "text-ax-text-secondary"}`}
            >
              {done ? (
                <Check className="text-ax-success size-4 shrink-0" aria-hidden="true" />
              ) : active ? (
                <Loader2
                  className="text-ax-text-accent size-4 shrink-0 motion-safe:animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <span
                  className="border-ax-border-strong size-3.5 shrink-0 rounded-full border"
                  aria-hidden="true"
                />
              )}
              <span>
                {done
                  ? t.rich("integration_progress_step_done_named", {
                      hidden: (chunks) => <span className="sr-only">{chunks}</span>,
                      step: t(PHASE_LABEL[phase])
                    })
                  : t(PHASE_LABEL[phase])}
              </span>
            </li>
          );
        })}
      </ol>

      {nowReading.length > 0 ? (
        <ul className="flex flex-col gap-1 text-sm">
          {nowReading.slice(0, 3).map((reading, index) => (
            <li key={index} className="flex min-w-0 items-center gap-2">
              <span className="text-ax-text-secondary shrink-0">
                {t("integration_progress_reading_in", { folder: reading.folder })}
              </span>
              <span className="min-w-0 truncate font-medium">{reading.file}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <p className="text-ax-text-secondary text-sm">{t("integration_progress_leave_page_hint")}</p>
    </section>
  );
}
