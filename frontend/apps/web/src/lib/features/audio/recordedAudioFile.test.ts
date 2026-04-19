import { describe, expect, it } from "vitest";

import { buildRecordedAudioFile } from "./recordedAudioFile";

describe("recordedAudioFile helpers", () => {
  it("uses m4a for mp4-based recordings", () => {
    const file = buildRecordedAudioFile({
      blob: new Blob(["audio"], { type: "audio/mp4" }),
      mimeType: "audio/mp4;codecs=avc1",
      fileNameBase: "recording"
    });

    expect(file.name).toBe("recording.m4a");
    expect(file.type).toBe("audio/mp4;codecs=avc1");
  });

  it("falls back to subtype extensions for other mime types", () => {
    const file = buildRecordedAudioFile({
      blob: new Blob(["audio"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      fileNameBase: "recording"
    });

    expect(file.name).toBe("recording.webm");
  });
});
