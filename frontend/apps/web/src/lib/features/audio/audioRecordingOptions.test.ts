import { describe, expect, it } from "vitest";

import {
  estimateRecordingBytes,
  estimateRecordingDurationSeconds,
  selectAudioRecordingOptions
} from "./audioRecordingOptions";

describe("audio recording options", () => {
  it("prefers Opus in an audio container for speech-sized recordings", () => {
    const options = selectAudioRecordingOptions((mimeType) =>
      ["audio/webm;codecs=opus", "audio/mp4"].includes(mimeType)
    );

    expect(options).toEqual({
      mimeType: "audio/webm;codecs=opus",
      audioBitsPerSecond: 24_000
    });
  });

  it("uses AAC audio rather than a video codec for Safari-style recording", () => {
    const options = selectAudioRecordingOptions(
      (mimeType) => mimeType === "audio/mp4;codecs=mp4a.40.2"
    );

    expect(options).toEqual({
      mimeType: "audio/mp4;codecs=mp4a.40.2",
      audioBitsPerSecond: 64_000
    });
  });

  it("falls back to bitrate-only options when the browser exposes no known MIME", () => {
    expect(selectAudioRecordingOptions(() => false)).toEqual({
      audioBitsPerSecond: 64_000
    });
  });

  it("estimates speech recording size from the configured bitrate", () => {
    expect(estimateRecordingBytes(60 * 60)).toBe(10_800_000);
    expect(estimateRecordingBytes(2 * 60 * 60)).toBe(21_600_000);
    expect(estimateRecordingBytes(3 * 60 * 60)).toBe(32_400_000);
  });

  it("estimates the available recording duration from a byte limit", () => {
    expect(estimateRecordingDurationSeconds(10 * 1024 * 1024)).toBe(3495);
  });
});
