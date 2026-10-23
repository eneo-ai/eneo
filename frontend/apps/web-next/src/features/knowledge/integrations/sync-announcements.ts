import {
  OUTCOME_WAIT_MS,
  problemCountChanged,
  SyncAnnouncer,
  type Snapshot,
  type Transition
} from "@eneo/eneo-js/integrations/sync-announcements";
import type { Translate } from "./skip-reasons";
import type { SourceSummary } from "./sources";

export {
  OUTCOME_WAIT_MS,
  PROGRESS_ANNOUNCE_INTERVAL_MS
} from "@eneo/eneo-js/integrations/sync-announcements";
export type { Snapshot } from "@eneo/eneo-js/integrations/sync-announcements";

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

function describe(name: string, transition: Transition, t: Translate): string {
  switch (transition.kind) {
    case "started":
      return t("integration_announce_sync_started", { name });
    case "queued":
      return t("integration_announce_sync_queued", { name });
    case "finished":
      return t("integration_announce_sync_finished", { name });
    case "failed":
      return t("integration_announce_sync_failed", { name });
    case "stopped":
      return t("integration_announce_sync_stopped", { name });
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

export type AnnouncedSource = { id: string; name: string; snapshot: Snapshot };

type Followed = { announcer: SyncAnnouncer; hadProgress: boolean; waitingSince: number | null };

/**
 * The announcements of a set of sources in the viewer's language, one
 * SyncAnnouncer each (it holds the rules). A sync's end waits for the rows to
 * record its outcome; `recheckAt` is when a wait runs out, so the caller can
 * feed the same sources again then and hear the end without an outcome.
 */
export class SourceAnnouncers {
  #options: ConstructorParameters<typeof SyncAnnouncer>[0];
  #followed = new Map<string, Followed>();

  constructor(options?: ConstructorParameters<typeof SyncAnnouncer>[0]) {
    this.#options = options;
  }

  next(
    sources: readonly AnnouncedSource[],
    now: number,
    t: Translate
  ): { messages: string[]; recheckAt: number | null } {
    const followed = new Map<string, Followed>();
    const messages: string[] = [];
    let recheckAt: number | null = null;
    for (const { id, name, snapshot } of sources) {
      const entry = this.#followed.get(id) ?? {
        announcer: new SyncAnnouncer(this.#options),
        hadProgress: false,
        waitingSince: null
      };
      const transition = entry.announcer.next(snapshot, now);
      if (snapshot.progress) {
        entry.waitingSince = null;
      } else if (entry.hadProgress) {
        entry.waitingSince = now;
      } else if (
        entry.waitingSince !== null &&
        (transition !== null || now - entry.waitingSince >= OUTCOME_WAIT_MS)
      ) {
        entry.waitingSince = null;
      }
      entry.hadProgress = snapshot.progress !== null;
      if (entry.waitingSince !== null) {
        const at = entry.waitingSince + OUTCOME_WAIT_MS;
        recheckAt = recheckAt === null ? at : Math.min(recheckAt, at);
      }
      if (transition) messages.push(describe(name, transition, t));
      followed.set(id, entry);
    }
    this.#followed = followed;
    return { messages, recheckAt };
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
