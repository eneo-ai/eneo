"use client";

import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { useTranslations } from "next-intl";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { StatusLabel } from "@/components/composites/status-label";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import type { IntegrationKnowledge } from "../knowledge";
import {
  itemWatchState,
  sourceStateStatus,
  type ItemState,
  type SourceState,
  type SourceSummary,
  type WatchState
} from "./sources";
import type { SyncProgressSummary } from "./sync-progress";

/**
 * The items' change notifications, null until hydrated: they are relative to
 * now, which the server and the browser see differently.
 */
export function useWatchStates(items: readonly IntegrationKnowledge[]): WatchState[] | null {
  const hydrated = useHydrated();
  return hydrated ? items.map((item) => itemWatchState(item)) : null;
}

/** A source's or item's state as a coloured dot and its label. */
export function SourceStateLabel({
  state,
  className
}: {
  state: SourceState | ItemState;
  className?: string;
}) {
  const t = useTranslations();
  const status = sourceStateStatus(state);
  return (
    <StatusLabel
      status={status.tone}
      label={t(status.labelKey)}
      isPulsing={status.isPulsing}
      className={className}
    />
  );
}

/** "12 of 40 files found so far are done" while a sync runs; the total may still grow. */
export function useProgressText() {
  const t = useTranslations();
  return (progress: Pick<SyncProgressSummary, "done" | "total">) =>
    progress.total === null
      ? t("integration_progress_syncing_so_far", { count: progress.done })
      : t("integration_progress_syncing_of_total", { done: progress.done, total: progress.total });
}

/**
 * A running sync of `name`: a bar (moving while the total is unknown) and the
 * files done so far. The bar's name says whose sync it is.
 */
export function SyncProgress({ progress, name }: { progress: SyncProgressSummary; name: string }) {
  const t = useTranslations();
  const progressText = useProgressText();
  const known = progress.total !== null && progress.total > 0;
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <ProgressBar
        label={t("integration_progress_label", { name })}
        isLabelHidden
        isIndeterminate={!known}
        value={known ? Math.min(progress.done, progress.total ?? 0) : 0}
        max={known ? (progress.total ?? 1) : 100}
      />
      <span className="text-ax-text-secondary text-xs tabular-nums">{progressText(progress)}</span>
    </div>
  );
}

/**
 * "Updating now" while the source syncs; otherwise when it was last up to
 * date, or when a sync was last tried if none ever finished.
 */
export function SourceUpdated({ summary }: { summary: SourceSummary }) {
  const t = useTranslations();
  const attempted = useClientTimeText(summary.lastSyncAttemptedAt, "date_time");
  return (
    <span className="text-ax-text-secondary text-sm">
      {summary.progress ? (
        t("integration_source_updating_now")
      ) : summary.lastSyncedAt ? (
        <ClientTime value={summary.lastSyncedAt} format="auto" />
      ) : attempted ? (
        t("integration_source_last_attempt_at", { time: attempted })
      ) : (
        "–"
      )}
    </span>
  );
}
