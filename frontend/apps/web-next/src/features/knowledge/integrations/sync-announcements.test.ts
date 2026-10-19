import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";
import sv from "@/lib/i18n/messages/sv.json";
import {
  announceProblemCount,
  announceSourceChange,
  PROGRESS_ANNOUNCE_INTERVAL_MS,
  type SourceSnapshot
} from "./sync-announcements";

const t = createTranslator({ locale: "sv", messages: sv as Record<string, string> });

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
    expect(announceSourceChange("Avtal", null, syncing(3), 60_000, t)).toBeNull();
  });

  it("speaks a queued, started and finished sync, the last with its counts", () => {
    expect(announceSourceChange("Avtal", idle, queued, 0, t)).toBe("Synk av Avtal köad");
    expect(announceSourceChange("Avtal", queued, syncing(1), 0, t)).toBe(
      "Synk av Avtal har startat"
    );
    expect(announceSourceChange("Avtal", syncing(40), idle, 0, t)).toBe(
      "Synk av Avtal klar: 39 sökbara, 1 kunde inte läsas"
    );
    expect(announceSourceChange("Avtal", queued, queued, 0, t)).toBeNull();
  });

  it("speaks the count at most every interval, and every phase change", () => {
    const soon = PROGRESS_ANNOUNCE_INTERVAL_MS - 1;
    expect(announceSourceChange("Avtal", syncing(3), syncing(5), soon, t)).toBeNull();
    expect(
      announceSourceChange("Avtal", syncing(3), syncing(5), PROGRESS_ANNOUNCE_INTERVAL_MS, t)
    ).toBe("Avtal: 5 av 40 lästa");
    expect(announceSourceChange("Avtal", syncing(5), syncing(5), 60_000, t)).toBeNull();
    expect(announceSourceChange("Avtal", syncing(40), syncing(40, "finishing"), 0, t)).toBe(
      "Avtal: 40 av 40 lästa"
    );
  });

  it("speaks a count without a total as read so far", () => {
    const unknownTotal: SourceSnapshot = {
      state: "syncing",
      progress: { phase: "processing", done: 7, total: null, indexed: 7, skipped: 0 }
    };
    expect(announceSourceChange("Avtal", syncing(3), unknownTotal, 60_000, t)).toBe(
      "Avtal: 7 lästa hittills"
    );
  });

  it("leaves the count to the source's page when speaking for a list", () => {
    const list = { speakProgress: false };
    expect(
      announceSourceChange("Avtal", syncing(3), syncing(30, "finishing"), 60_000, t, list)
    ).toBeNull();
    expect(announceSourceChange("Avtal", idle, syncing(1), 0, t, list)).toBe(
      "Synk av Avtal har startat"
    );
    expect(announceSourceChange("Avtal", idle, queued, 0, t, list)).toBe("Synk av Avtal köad");
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
