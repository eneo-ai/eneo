import {
  SyncAnnouncer,
  problemCountChanged,
  type Snapshot,
  type Transition
} from "@eneo/eneo-js/integrations/sync-announcements";
import { m } from "$lib/paraglide/messages";
import type { SourceSummary } from "./sources";

export {
  OUTCOME_WAIT_MS,
  PROGRESS_ANNOUNCE_INTERVAL_MS
} from "@eneo/eneo-js/integrations/sync-announcements";

type AnnouncedSummary = Pick<
  SourceSummary,
  "state" | "progress" | "lastSyncedAt" | "lastSyncAttemptedAt" | "failedItems"
>;

/** What of a source's summary its announcements follow. */
export function sourceSnapshot(summary: AnnouncedSummary): Snapshot {
  const { progress } = summary;
  return {
    state: summary.state,
    progress: progress && {
      phase: progress.phase,
      done: progress.done,
      total: progress.total,
      background: progress.background
    },
    outcome: [
      summary.lastSyncedAt ?? "",
      summary.lastSyncAttemptedAt ?? "",
      ...summary.failedItems.map((item) => item.id).sort()
    ].join("|"),
    failures: summary.failedItems.map(
      (item) => `${item.id}@${item.metadata?.last_sync_attempted_at ?? ""}`
    )
  };
}

function describe(name: string, transition: Transition): string {
  switch (transition.kind) {
    case "started":
      return m.integration_announce_sync_started({ name });
    case "queued":
      return m.integration_announce_sync_queued({ name });
    case "finished":
      return m.integration_announce_sync_finished({ name });
    case "failed":
      return m.integration_announce_sync_failed({ name });
    case "stopped":
      return m.integration_announce_sync_stopped({ name });
    case "progress":
      return transition.total === null
        ? m.integration_announce_sync_progress({ name, count: transition.done })
        : m.integration_announce_sync_progress_total({
            name,
            done: transition.done,
            total: transition.total
          });
  }
}

/** One source's announcements in the viewer's language; SyncAnnouncer holds the rules. */
export class SourceAnnouncer {
  #announcer: SyncAnnouncer;

  constructor(options?: ConstructorParameters<typeof SyncAnnouncer>[0]) {
    this.#announcer = new SyncAnnouncer(options);
  }

  /** When an ended sync stops waiting for its outcome; call `next` again then. */
  get awaitingUntil(): number | null {
    return this.#announcer.awaitingUntil;
  }

  next(name: string, summary: AnnouncedSummary, now: number): string | null {
    const transition = this.#announcer.next(sourceSnapshot(summary), now);
    return transition ? describe(name, transition) : null;
  }
}

/** A spoken note when the number of problems changes once the lists are known. */
export function announceProblemCount(previous: number | null, next: number | null): string | null {
  if (!problemCountChanged(previous, next) || next === null) return null;
  return m.integration_announce_problems({ count: next });
}
