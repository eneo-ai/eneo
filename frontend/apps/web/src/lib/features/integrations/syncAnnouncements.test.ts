import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import {
  PROGRESS_ANNOUNCE_INTERVAL_MS,
  announceProblemCount,
  announceSourceChange,
  type SourceSnapshot
} from "./syncAnnouncements";

const idle: SourceSnapshot = { state: "ok", progress: null };
const queued: SourceSnapshot = { state: "queued", progress: null };

function syncing(done: number, phase: "processing" | "finishing" = "processing"): SourceSnapshot {
  return {
    state: "syncing",
    progress: { phase, done, total: 40, indexed: done - 1, skipped: 1 }
  };
}

describe("announceSourceChange", () => {
  it("says nothing about the state a page opens with", () => {
    expect(announceSourceChange("Avtal", null, syncing(3), 60_000)).toBeNull();
  });

  it("speaks a queued, started and finished sync", () => {
    expect(announceSourceChange("Avtal", idle, queued, 0)).toBe(
      m.integration_announce_sync_queued({ name: "Avtal" })
    );
    expect(announceSourceChange("Avtal", queued, syncing(1), 0)).toBe(
      m.integration_announce_sync_started({ name: "Avtal" })
    );
    expect(announceSourceChange("Avtal", syncing(40), idle, 0)).toBe(
      m.integration_announce_sync_finished({ name: "Avtal", indexed: 39, skipped: 1 })
    );
  });

  it("speaks the count at most every interval, and every phase change", () => {
    const soon = PROGRESS_ANNOUNCE_INTERVAL_MS - 1;
    expect(announceSourceChange("Avtal", syncing(3), syncing(5), soon)).toBeNull();
    expect(
      announceSourceChange("Avtal", syncing(3), syncing(5), PROGRESS_ANNOUNCE_INTERVAL_MS)
    ).toBe(m.integration_announce_sync_progress_total({ name: "Avtal", done: 5, total: 40 }));
    expect(announceSourceChange("Avtal", syncing(5), syncing(5), 60_000)).toBeNull();
    expect(announceSourceChange("Avtal", syncing(40), syncing(40, "finishing"), 0)).toBe(
      m.integration_announce_sync_progress_total({ name: "Avtal", done: 40, total: 40 })
    );
  });

  it("speaks a count without a total as read so far", () => {
    const unknownTotal: SourceSnapshot = {
      state: "syncing",
      progress: { phase: "processing", done: 7, total: null, indexed: 7, skipped: 0 }
    };
    expect(announceSourceChange("Avtal", syncing(3), unknownTotal, 60_000)).toBe(
      m.integration_announce_sync_progress({ name: "Avtal", count: 7 })
    );
  });

  it("leaves the count to the source's page when speaking for a list", () => {
    expect(
      announceSourceChange("Avtal", syncing(3), syncing(30, "finishing"), 60_000, {
        speakProgress: false
      })
    ).toBeNull();
    expect(announceSourceChange("Avtal", idle, syncing(1), 0, { speakProgress: false })).toBe(
      m.integration_announce_sync_started({ name: "Avtal" })
    );
  });
});

describe("announceProblemCount", () => {
  it("speaks a change once the lists are known", () => {
    expect(announceProblemCount(null, 2)).toBeNull();
    expect(announceProblemCount(2, null)).toBeNull();
    expect(announceProblemCount(2, 2)).toBeNull();
    expect(announceProblemCount(2, 3)).toBe(m.integration_announce_problems({ count: 3 }));
  });
});
