"use client";

import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { useTranslations } from "use-intl";
import { useEffect, useState } from "react";
import { formatSeconds } from "./run-format";
import { runStepProgress, type RunStepView } from "./run-progress";
import { runStatusView, shouldPoll } from "./run-status";
import type { RunSummary } from "./runs-api";

/** The time since the run started, counted up each second while it runs. */
function Elapsed({ startedAt, ticking }: { startedAt: string; ticking: boolean }) {
  const t = useTranslations();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!ticking) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [ticking]);
  const started = Date.parse(startedAt);
  if (!Number.isFinite(started)) return null;
  return (
    <span className="text-ax-text-secondary text-sm tabular-nums">
      {t("flow_run_progress_elapsed", {
        elapsed: formatSeconds(Math.max(0, now - started) / 1000, t)
      })}
    </span>
  );
}

/**
 * How far a run that is still under way has come: "step N of M" with what
 * it is doing, a progress bar over the steps that ended, and the time since
 * it started, counted up while it runs. Shown only while the run moves (the
 * status capability's `should_poll`); a finished run's header says how
 * long it took.
 */
export function RunLiveProgress({
  summary,
  steps
}: {
  summary: Pick<RunSummary, "status" | "started_at">;
  steps: readonly RunStepView[];
}) {
  const t = useTranslations();
  const progress = runStepProgress(steps);
  if (!shouldPoll(summary.status) || progress.total === 0) return null;
  const counter = t("flow_run_progress_counter", {
    current: progress.current,
    total: progress.total
  });
  const doing =
    summary.status === "awaiting_review"
      ? t(runStatusView(summary.status).labelKey)
      : progress.running > 0
        ? t("flow_run_progress_running_summary")
        : t("flow_run_progress_pending_summary");
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-ax-text m-0 text-sm">
          <span className="font-medium tabular-nums">{counter}</span>
          <span className="text-ax-text-secondary"> · {doing}</span>
        </p>
        {summary.started_at ? (
          <Elapsed startedAt={summary.started_at} ticking={summary.status === "running"} />
        ) : null}
      </div>
      <ProgressBar
        label={t("flow_run_journey_progress")}
        isLabelHidden
        value={progress.ended}
        max={progress.total}
      />
    </div>
  );
}
