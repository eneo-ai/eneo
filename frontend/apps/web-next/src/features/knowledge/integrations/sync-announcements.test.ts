import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";
import sv from "@/lib/i18n/messages/sv.json";
import type { IntegrationKnowledge } from "../knowledge";
import type { SourceSummary } from "./sources";
import type { SyncProgressPhase } from "./sync-progress";
import {
  announceProblemCount,
  OUTCOME_WAIT_MS,
  PROGRESS_ANNOUNCE_INTERVAL_MS,
  SourceAnnouncers,
  sourceSnapshot
} from "./sync-announcements";

const t = createTranslator({ locale: "sv", messages: sv as Record<string, string> });

type Summary = Pick<
  SourceSummary,
  "state" | "progress" | "lastSyncedAt" | "lastSyncAttemptedAt" | "failedItems"
>;

const failing = (attemptedAt = "2026-10-19T08:00:00Z") =>
  ({ id: "b", metadata: { size: 0, last_sync_attempted_at: attemptedAt } }) as IntegrationKnowledge;

function idle(lastSyncedAt = "2026-10-19T08:00:00Z", failedAt: string | null = null): Summary {
  return {
    state: failedAt ? "attention" : "ok",
    progress: null,
    lastSyncedAt,
    lastSyncAttemptedAt: lastSyncedAt,
    failedItems: failedAt ? [failing(failedAt)] : []
  };
}

function syncing(
  done: number,
  {
    background = false,
    phase = "processing"
  }: { background?: boolean; phase?: SyncProgressPhase } = {}
): Summary {
  return {
    ...idle(),
    state: "syncing",
    progress: {
      phase,
      startedAt: "2026-10-19T09:00:00Z",
      total: 40,
      done,
      indexed: done,
      unchanged: 0,
      skipped: 0,
      syncing: 1,
      background
    }
  };
}

const queued = (): Summary => ({ ...idle(), state: "queued" });

/** One source's announcer; `next` returns what is said, or null. */
function source(options?: ConstructorParameters<typeof SourceAnnouncers>[0]) {
  const announcers = new SourceAnnouncers(options);
  return {
    next: (summary: Summary, now: number) => {
      const { messages } = announcers.next(
        [{ id: "a", name: "Avtal", snapshot: sourceSnapshot(summary) }],
        now,
        t
      );
      return messages[0] ?? null;
    },
    recheckAt: (summary: Summary, now: number) =>
      announcers.next([{ id: "a", name: "Avtal", snapshot: sourceSnapshot(summary) }], now, t)
        .recheckAt
  };
}

describe("SourceAnnouncers", () => {
  it("speaks a sync's course and how it ended once the rows say so", () => {
    const avtal = source();
    expect(avtal.next(idle(), 0)).toBeNull();
    expect(avtal.next(syncing(1), 1_000)).toBe("Synk av Avtal har startat");
    expect(avtal.next(syncing(5), 2_000)).toBeNull();
    expect(avtal.next(syncing(9), 1_000 + PROGRESS_ANNOUNCE_INTERVAL_MS)).toBe(
      "Avtal: 9 av 40 lästa"
    );
    // The progress is gone before the space's rows are read again.
    expect(avtal.next(idle(), 20_000)).toBeNull();
    expect(avtal.next(idle("2026-10-19T09:05:00Z"), 21_000)).toBe("Synk av Avtal klar");
  });

  it("speaks reaching the last step, and a queued sync", () => {
    const avtal = source();
    avtal.next(idle(), 0);
    expect(avtal.next(queued(), 500)).toBe("Synk av Avtal köad");
    expect(avtal.next(queued(), 600)).toBeNull();
    avtal.next(syncing(39), 1_000);
    expect(avtal.next(syncing(40, { phase: "finishing" }), 2_000)).toBe("Avtal: 40 av 40 lästa");
  });

  it("says a sync failed when its rows record a failure", () => {
    const avtal = source();
    avtal.next(idle(), 0);
    avtal.next(syncing(1), 1_000);
    avtal.next(idle(), 2_000);
    expect(avtal.next(idle(undefined, "2026-10-19T09:01:00Z"), 3_000)).toBe(
      "Synk av Avtal misslyckades"
    );
  });

  it("does not blame a sync for a folder that was failing before it and was not tried", () => {
    const before = "2026-10-19T07:00:00Z";
    const avtal = source();
    avtal.next(idle(undefined, before), 0);
    avtal.next({ ...syncing(1), failedItems: [failing(before)] }, 1_000);
    avtal.next(idle(undefined, before), 2_000);
    expect(avtal.next(idle("2026-10-19T09:05:00Z", before), 3_000)).toBe("Synk av Avtal klar");
  });

  it("asks to be looked at again when the rows may not say, then ends without an outcome", () => {
    const avtal = source();
    avtal.next(idle(), 0);
    avtal.next(syncing(1), 1_000);
    expect(avtal.recheckAt(idle(), 2_000)).toBe(2_000 + OUTCOME_WAIT_MS);
    expect(avtal.next(idle(), 2_000 + OUTCOME_WAIT_MS)).toBe("Synk av Avtal pågår inte längre");
    expect(avtal.recheckAt(idle(), 2_000 + OUTCOME_WAIT_MS)).toBeNull();
  });

  it("keeps a change notification's sync quiet, and stops looking for its end", () => {
    const avtal = source();
    avtal.next(idle(), 0);
    expect(avtal.next(syncing(1, { background: true }), 1_000)).toBeNull();
    expect(avtal.next(idle(), 2_000)).toBeNull();
    expect(avtal.recheckAt(idle(), 2_000 + OUTCOME_WAIT_MS)).toBeNull();
    expect(avtal.next(idle("2026-10-19T09:05:00Z"), 3_000 + OUTCOME_WAIT_MS)).toBeNull();
  });

  it("speaks for a list only a sync it saw queued, without counts", () => {
    const avtal = source({ speakProgress: false, onlyStartedHere: true });
    avtal.next(idle(), 0);
    expect(avtal.next(syncing(1), 1_000)).toBeNull();
    avtal.next(idle(), 2_000);
    expect(avtal.next(queued(), 3_000)).toBe("Synk av Avtal köad");
    expect(avtal.next(syncing(1), 4_000)).toBe("Synk av Avtal har startat");
    expect(avtal.next(syncing(30), 4_000 + PROGRESS_ANNOUNCE_INTERVAL_MS)).toBeNull();
    avtal.next(idle(), 20_000);
    expect(avtal.next(idle("2026-10-19T09:05:00Z"), 21_000)).toBe("Synk av Avtal klar");
  });

  it("follows every source on its own and forgets the ones that went", () => {
    const announcers = new SourceAnnouncers();
    const pair = (a: Summary, b: Summary) => [
      { id: "a", name: "Avtal", snapshot: sourceSnapshot(a) },
      { id: "b", name: "Policy", snapshot: sourceSnapshot(b) }
    ];
    announcers.next(pair(idle(), idle()), 0, t);
    expect(announcers.next(pair(queued(), queued()), 1_000, t).messages).toEqual([
      "Synk av Avtal köad",
      "Synk av Policy köad"
    ]);
    announcers.next([], 2_000, t);
    // Back again: its first snapshot is not news.
    expect(announcers.next(pair(syncing(1), syncing(1)), 3_000, t).messages).toEqual([]);
  });
});

describe("sourceSnapshot", () => {
  it("signs the recorded outcome by its times and failing items", () => {
    expect(sourceSnapshot(idle()).outcome).not.toBe(
      sourceSnapshot(idle("2026-10-19T09:05:00Z")).outcome
    );
    expect(sourceSnapshot(idle(undefined, "2026-10-19T09:01:00Z")).failures).toEqual([
      "b@2026-10-19T09:01:00Z"
    ]);
    expect(sourceSnapshot(syncing(3, { background: true })).progress).toMatchObject({
      background: true
    });
  });
});

describe("announceProblemCount", () => {
  it("speaks a change once the lists are known", () => {
    expect(announceProblemCount(null, 2, t)).toBeNull();
    expect(announceProblemCount(2, null, t)).toBeNull();
    expect(announceProblemCount(2, 2, t)).toBeNull();
    expect(announceProblemCount(2, 3, t)).toBe("Problem: 3");
  });
});
