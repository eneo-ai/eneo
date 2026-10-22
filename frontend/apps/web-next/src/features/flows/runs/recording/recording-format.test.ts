import { describe, expect, it } from "vitest";
import {
  clockText,
  partFileName,
  recordingLimits,
  recordingTimeLeftMs,
  recordsInto,
  selectRecordingOptions
} from "./recording-format";

describe("selectRecordingOptions", () => {
  it("takes the first speech format the browser records", () => {
    expect(selectRecordingOptions((type) => type.startsWith("audio/mp4"))).toEqual({
      mimeType: "audio/mp4;codecs=mp4a.40.2",
      audioBitsPerSecond: 64_000
    });
    expect(
      selectRecordingOptions(() => {
        throw new Error("unsupported");
      })
    ).toEqual({ audioBitsPerSecond: 64_000 });
  });
});

describe("partFileName", () => {
  it("names a part as the core reads recording parts back", () => {
    const name = partFileName("4f1c2b", 3, Date.UTC(2026, 9, 22, 8, 5, 9, 120), "audio/webm");
    expect(name).toBe("recording-4f1c2b-seg03-2026-10-22T08-05-09-120Z.webm");
    expect(name).toMatch(
      /^recording-[0-9a-fA-F-]+-seg\d{2,4}-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-\d+)?Z\.[A-Za-z0-9]+$/
    );
  });
});

describe("recordsInto", () => {
  it("records only into audio steps that take the recorded type", () => {
    const audio = { input_format: "audio" as const, accepted_mimetypes: ["audio/webm"] };
    expect(recordsInto(audio, "audio/webm;codecs=opus")).toBe(true);
    expect(recordsInto(audio, "audio/mp4")).toBe(false);
    expect(recordsInto({ ...audio, accepted_mimetypes: ["audio/*"] }, "audio/mp4")).toBe(true);
    expect(recordsInto({ input_format: "document", accepted_mimetypes: [] }, "audio/webm")).toBe(
      false
    );
  });
});

describe("recordingLimits", () => {
  it("takes the contract's part length and longest recording", () => {
    expect(
      recordingLimits(
        {
          max_files: 10,
          max_duration_seconds: 18_000,
          max_recording_seconds: 21_600,
          recording_part_seconds: 2_160
        },
        24_000
      )
    ).toEqual({ partMs: 2_160_000, maxRecordingMs: 21_600_000 });
  });

  it("starts a part before it nears the size one file may hold", () => {
    const limits = recordingLimits(
      {
        max_files: 5,
        max_file_size_bytes: 25_000_000,
        max_recording_seconds: 18_000,
        recording_part_seconds: 3_600
      },
      64_000
    );
    expect(limits).toEqual({ partMs: 2_812_500, maxRecordingMs: 18_000_000 });
  });

  it("leaves a recording unbounded without limits", () => {
    expect(recordingLimits({ max_files: null }, 24_000)).toEqual({
      partMs: null,
      maxRecordingMs: null
    });
    expect(recordingTimeLeftMs(null, 1, 60_000)).toBe(Infinity);
  });

  it("keeps room below the longest recording for late timers and handovers", () => {
    // An hour leaves a minute of room, and a second per handover.
    expect(recordingTimeLeftMs(3_600_000, 3, 1_000_000)).toBe(
      3_600_000 - 60_000 - 2_000 - 1_000_000
    );
  });
});

describe("clockText", () => {
  it("shows minutes and seconds, and hours once there are any", () => {
    expect(clockText(65_400)).toBe("01:05");
    expect(clockText(3_725_000)).toBe("1:02:05");
  });
});
