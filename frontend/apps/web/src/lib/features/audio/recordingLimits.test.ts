import { describe, expect, it } from "vitest";
import {
  formatRecordingLength,
  recordingLimitsForStep,
  recordingRoomMs,
  recordingTimeLeftMs
} from "./recordingLimits";

const HOUR = 3_600_000;
const OPUS = 24_000;

describe("recordingLimitsForStep", () => {
  it("takes Eneo's longest recording and part length", () => {
    expect(
      recordingLimitsForStep(
        {
          max_files: 10,
          max_duration_seconds: 18_000,
          max_recording_seconds: 21_600,
          recording_part_seconds: 2_160
        },
        OPUS
      )
    ).toEqual({ partMs: 2_160_000, maxRecordingMs: 21_600_000 });
  });

  it("reads an older Eneo's time per file as the whole recording's, spread over the file slots", () => {
    expect(recordingLimitsForStep({ max_files: 10, max_duration_seconds: 18_000 }, OPUS)).toEqual({
      partMs: 1_800_000,
      maxRecordingMs: 18_000_000
    });
    expect(recordingLimitsForStep({ max_files: null }, OPUS)).toEqual({
      partMs: null,
      maxRecordingMs: null
    });
  });

  it("starts a part before it nears what one file may hold, as Eneo's contract asks", () => {
    // 25 MB at 64 kbps (AAC) is 52 min; a tenth is kept for the codec's swings.
    const bySize = recordingLimitsForStep(
      {
        max_files: 5,
        max_file_size_bytes: 25_000_000,
        max_recording_seconds: 18_000,
        recording_part_seconds: 3_600
      },
      64_000
    );
    expect(bySize).toEqual({ partMs: 2_812_500, maxRecordingMs: 18_000_000 });
    // 20 min per file, with a minute's room.
    const byTime = recordingLimitsForStep(
      {
        max_files: 10,
        max_duration_seconds: 1_200,
        max_recording_seconds: 18_000,
        recording_part_seconds: 1_800
      },
      OPUS
    );
    expect(byTime.partMs).toBe(1_140_000);
  });
});

describe("recordingRoomMs", () => {
  it("is Eneo's limit for a new recording, what a continued one may still record, within the free slots", () => {
    const limits = {
      partMs: 0.5 * HOUR,
      maxRecordingMs: 5 * HOUR,
      recordedMs: 0,
      parts: 0,
      filesLeft: 10
    };
    expect(recordingRoomMs(limits)).toBe(5 * HOUR);
    // A file chosen already takes a slot.
    expect(recordingRoomMs({ ...limits, filesLeft: 9 })).toBe(4.5 * HOUR);
    // Nine parts, 4 h 45 min: the minute's room and nine handovers' seconds come off, as when it stops.
    expect(recordingRoomMs({ ...limits, recordedMs: 4.75 * HOUR, parts: 9, filesLeft: 1 })).toBe(
      0.25 * HOUR - 60_000 - 9_000
    );
    expect(
      recordingRoomMs({ partMs: null, maxRecordingMs: null, recordedMs: 0, parts: 0, filesLeft: 3 })
    ).toBeNull();
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
