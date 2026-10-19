import { m } from "$lib/paraglide/messages";
import type { SourceState } from "./sources";
import type { SyncProgressSummary } from "./syncProgress";

/** A running sync's count is spoken at most this often; phase changes always are. */
export const PROGRESS_ANNOUNCE_INTERVAL_MS = 10_000;

export type SourceSnapshot = {
  state: SourceState;
  progress: Pick<SyncProgressSummary, "phase" | "done" | "total" | "indexed" | "skipped"> | null;
};

/**
 * What a screen reader should hear when a source's sync state moves from
 * `previous` to `next`, or null. The first snapshot of a page is not news.
 * `sinceProgressAnnounced` is the time since the last spoken progress count;
 * a list of many sources passes `speakProgress: false` and says only when
 * syncs start, finish or queue.
 */
export function announceSourceChange(
  name: string,
  previous: SourceSnapshot | null,
  next: SourceSnapshot,
  sinceProgressAnnounced: number,
  { speakProgress = true }: { speakProgress?: boolean } = {}
): string | null {
  if (!previous) return null;
  const was = previous.progress;
  const now = next.progress;
  if (now && !was) return m.integration_announce_sync_started({ name });
  if (!now && was) {
    return m.integration_announce_sync_finished({
      name,
      indexed: was.indexed,
      skipped: was.skipped
    });
  }
  if (now && was) {
    if (!speakProgress) return null;
    const phaseChanged = now.phase !== was.phase;
    const moved = now.done !== was.done;
    if (!phaseChanged && (!moved || sinceProgressAnnounced < PROGRESS_ANNOUNCE_INTERVAL_MS)) {
      return null;
    }
    return now.total === null
      ? m.integration_announce_sync_progress({ name, count: now.done })
      : m.integration_announce_sync_progress_total({ name, done: now.done, total: now.total });
  }
  if (next.state === "queued" && previous.state !== "queued") {
    return m.integration_announce_sync_queued({ name });
  }
  return null;
}

/** A spoken note when the number of problems changes once the lists are known. */
export function announceProblemCount(previous: number | null, next: number | null): string | null {
  if (previous === null || next === null || previous === next) return null;
  return m.integration_announce_problems({ count: next });
}
