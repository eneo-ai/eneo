import { describe, expect, it } from "vitest";
import { parseSegments, shownSegments } from "./transcript";
import { exportClock, transcriptText } from "./transcript-export";

const words = {
  part: (n: number) => `Del ${n}`,
  unknownSpeaker: "Okänd talare",
  unsureSpeaker: "osäker"
};

describe("transcriptText", () => {
  it("writes the transcript as the reader sees it, one line per speaker part", () => {
    const lines = parseSegments([
      {
        segment_index: 0,
        file_index: 0,
        start: 0,
        end: 4,
        speaker: "SPEAKER_00",
        text: "Hej Sugary."
      },
      { segment_index: 1, file_index: 1, start: 3_700, end: 3_705, speaker: null, text: "Ja." },
      {
        segment_index: 2,
        file_index: 1,
        start: 3_710,
        end: 3_712,
        speaker: "SPEAKER_01",
        text: "Kanske.",
        speaker_attribution: "provisional"
      }
    ]);
    const shown = shownSegments(lines, {
      occurrences: [
        { segment_index: 0, char_start: 4, char_end: 10, original: "Sugary", corrected: "Çagri" }
      ],
      speaker_edits: [],
      speaker_names: { SPEAKER_00: "Anna" }
    });
    expect(transcriptText(shown, words)).toBe(
      [
        "## Del 1",
        "",
        "[00:00:00 - 00:00:04] Anna: Hej Çagri.",
        "",
        "## Del 2",
        "",
        "[01:01:40 - 01:01:45] Okänd talare: Ja.",
        "[01:01:50 - 01:01:52] SPEAKER_01 (osäker): Kanske.",
        ""
      ].join("\n")
    );
  });

  it("writes hours always", () => {
    expect(exportClock(65.9)).toBe("00:01:05");
  });
});
