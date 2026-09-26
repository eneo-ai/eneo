import { describe, expect, it } from "vitest";
import {
  formatRecordingLength,
  recordingLimitsForStep,
  recordingTimeLeftMs
} from "./recordingLimits";

const HOUR = 3_600_000;

describe("recordingLimitsForStep", () => {
  it("takes Eneo's longest recording and part length", () => {
    expect(
      recordingLimitsForStep({
        max_files: 10,
        max_duration_seconds: 18_000,
        max_recording_seconds: 21_600,
        recording_part_seconds: 2_160
      })
    ).toEqual({ partMs: 2_160_000, maxRecordingMs: 21_600_000 });
  });

  it("reads an older Eneo's time per file as the whole recording's, spread over the file slots", () => {
    expect(recordingLimitsForStep({ max_files: 10, max_duration_seconds: 18_000 })).toEqual({
      partMs: 1_800_000,
      maxRecordingMs: 18_000_000
    });
    expect(recordingLimitsForStep({ max_files: null })).toEqual({
      partMs: null,
      maxRecordingMs: null
    });
  });
});

describe("recordingTimeLeftMs", () => {
  it("keeps a minute's room and a second per handover", () => {
    expect(recordingTimeLeftMs(5 * HOUR, 1, 0)).toBe(5 * HOUR - 60_000);
    expect(recordingTimeLeftMs(5 * HOUR, 10, 4.5 * HOUR)).toBe(0.5 * HOUR - 60_000 - 9_000);
    expect(recordingTimeLeftMs(null, 3, HOUR)).toBe(Infinity);
  });
});

describe("formatRecordingLength", () => {
  it("says hours and minutes", () => {
    expect([5 * HOUR, 4.5 * HOUR, 45 * 60_000].map(formatRecordingLength)).toEqual([
      "5 h",
      "4 h 30 min",
      "45 min"
    ]);
  });
});
