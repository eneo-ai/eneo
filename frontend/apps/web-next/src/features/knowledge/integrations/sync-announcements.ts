import {
  syncAnnouncement,
  problemCountChanged,
  PROGRESS_ANNOUNCE_INTERVAL_MS
} from "@eneo/eneo-js/integrations/sync-announcements";
export { PROGRESS_ANNOUNCE_INTERVAL_MS };
import type { Translate } from "./skip-reasons";
import type { SourceState, SourceSummary } from "./sources";
import type { SyncProgressSummary } from "./sync-progress";

export type SourceSnapshot = {
  state: SourceState;
  progress: Pick<SyncProgressSummary, "phase" | "done" | "total" | "indexed" | "skipped"> | null;
};

/** What of a source's summary its announcements follow. */
export function sourceSnapshot(summary: Pick<SourceSummary, "state" | "progress">): SourceSnapshot {
  const { progress } = summary;
  return {
    state: summary.state,
    progress: progress && {
      phase: progress.phase,
      done: progress.done,
      total: progress.total,
      indexed: progress.indexed,
      skipped: progress.skipped
    }
  };
}

/**
 * What a screen reader should hear when a source's sync state moves from
 * `previous` to `next`, or null. The first snapshot of a page is not news.
 * `sinceProgressAnnounced` is the time since the last spoken progress count;
 * a list of many sources passes `speakProgress: false` and says only when
 * syncs start, stop or queue.
 */
export function announceSourceChange(
  name: string,
  previous: SourceSnapshot | null,
  next: SourceSnapshot,
  sinceProgressAnnounced: number,
  t: Translate,
  { speakProgress = true }: { speakProgress?: boolean } = {}
): string | null {
  const transition = syncAnnouncement(previous, next, sinceProgressAnnounced, { speakProgress });
  if (!transition) return null;
  switch (transition.kind) {
    case "started":
      return t("integration_announce_sync_started", { name });
    case "stopped":
      return t("integration_announce_sync_stopped", { name });
    case "queued":
      return t("integration_announce_sync_queued", { name });
    case "progress":
      return transition.total === null
        ? t("integration_announce_sync_progress", { name, count: transition.done })
        : t("integration_announce_sync_progress_total", {
            name,
            done: transition.done,
            total: transition.total
          });
  }
}

/** A spoken note when the number of problems changes once the lists are known. */
export function announceProblemCount(
  previous: number | null,
  next: number | null,
  t: Translate
): string | null {
  if (!problemCountChanged(previous, next) || next === null) return null;
  return t("integration_announce_problems", { count: next });
}
