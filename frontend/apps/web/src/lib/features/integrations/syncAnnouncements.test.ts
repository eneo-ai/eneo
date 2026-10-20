import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import type { SourceSummary } from "./sources";
import {
  OUTCOME_WAIT_MS,
  PROGRESS_ANNOUNCE_INTERVAL_MS,
  SourceAnnouncer,
  announceProblemCount,
  sourceSnapshot
} from "./syncAnnouncements";

type Summary = Pick<
  SourceSummary,
  "state" | "progress" | "lastSyncedAt" | "lastSyncAttemptedAt" | "failedItems"
>;

const failing = (attemptedAt = "2026-10-19T08:00:00Z") =>
  ({ id: "b", metadata: { last_sync_attempted_at: attemptedAt } }) as IntegrationKnowledge;

function idle(lastSyncedAt = "2026-10-19T08:00:00Z", failedAt: string | null = null): Summary {
  return {
    state: failedAt ? "attention" : "ok",
    progress: null,
    lastSyncedAt,
    lastSyncAttemptedAt: lastSyncedAt,
    failedItems: failedAt ? [failing(failedAt)] : []
  };
}

function syncing(done: number, background = false): Summary {
  return {
    ...idle(),
    state: "syncing",
    progress: {
      phase: "processing",
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

describe("SourceAnnouncer", () => {
  it("speaks a sync's course and how it ended once the rows say so", () => {
    const announcer = new SourceAnnouncer();
    expect(announcer.next("Avtal", idle(), 0)).toBeNull();
    expect(announcer.next("Avtal", syncing(1), 1_000)).toBe(
      m.integration_announce_sync_started({ name: "Avtal" })
    );
    expect(announcer.next("Avtal", syncing(9), 1_000 + PROGRESS_ANNOUNCE_INTERVAL_MS)).toBe(
      m.integration_announce_sync_progress_total({ name: "Avtal", done: 9, total: 40 })
    );
    // The progress is gone before the space's rows are read again.
    expect(announcer.next("Avtal", idle(), 20_000)).toBeNull();
    expect(announcer.next("Avtal", idle("2026-10-19T09:05:00Z"), 21_000)).toBe(
      m.integration_announce_sync_finished({ name: "Avtal" })
    );
  });

  it("says a sync failed when its rows record a failure", () => {
    const announcer = new SourceAnnouncer();
    announcer.next("Avtal", idle(), 0);
    announcer.next("Avtal", syncing(1), 1_000);
    announcer.next("Avtal", idle(), 2_000);
    expect(announcer.next("Avtal", idle(undefined, "2026-10-19T09:01:00Z"), 3_000)).toBe(
      m.integration_announce_sync_failed({ name: "Avtal" })
    );
  });

  it("does not blame a sync for a folder that was failing before it and was not tried", () => {
    const before = "2026-10-19T07:00:00Z";
    const announcer = new SourceAnnouncer();
    announcer.next("Avtal", idle(undefined, before), 0);
    announcer.next("Avtal", { ...syncing(1), failedItems: [failing(before)] }, 1_000);
    announcer.next("Avtal", idle(undefined, before), 2_000);
    expect(announcer.next("Avtal", idle("2026-10-19T09:05:00Z", before), 3_000)).toBe(
      m.integration_announce_sync_finished({ name: "Avtal" })
    );
  });

  it("falls back to an end without an outcome when the rows never change", () => {
    const announcer = new SourceAnnouncer();
    announcer.next("Avtal", idle(), 0);
    announcer.next("Avtal", syncing(1), 1_000);
    announcer.next("Avtal", idle(), 2_000);
    expect(announcer.next("Avtal", idle(), 2_000 + OUTCOME_WAIT_MS)).toBe(
      m.integration_announce_sync_stopped({ name: "Avtal" })
    );
  });

  it("keeps a change notification's sync quiet", () => {
    const announcer = new SourceAnnouncer();
    announcer.next("Avtal", idle(), 0);
    expect(announcer.next("Avtal", syncing(1, true), 1_000)).toBeNull();
    expect(announcer.next("Avtal", idle(), 2_000)).toBeNull();
    expect(announcer.next("Avtal", idle("2026-10-19T09:05:00Z"), 3_000)).toBeNull();
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
    expect(sourceSnapshot(syncing(3, true)).progress).toMatchObject({ background: true });
  });
});

describe("announceProblemCount", () => {
  it("speaks a change once the lists are known", () => {
    expect(announceProblemCount(null, 2)).toBeNull();
    expect(announceProblemCount(2, 2)).toBeNull();
    expect(announceProblemCount(2, 3)).toBe(m.integration_announce_problems({ count: 3 }));
  });
});
