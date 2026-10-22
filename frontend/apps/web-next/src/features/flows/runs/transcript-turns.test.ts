import { describe, expect, it } from "vitest";
import { parseSegments, shownSegments } from "./transcript";
import { transcriptTurns } from "./transcript-turns";

const segment = (
  index: number,
  speaker: string | null,
  text: string,
  extra: { file_index?: number; speaker_attribution?: "provisional" } = {}
) => ({
  segment_index: index,
  file_index: extra.file_index ?? 0,
  start: index * 5,
  end: index * 5 + 4,
  speaker,
  text,
  ...(extra.speaker_attribution ? { speaker_attribution: extra.speaker_attribution } : {})
});

describe("transcriptTurns", () => {
  it("joins what one speaker said in a row, and starts a turn at a new speaker or file", () => {
    const lines = parseSegments([
      segment(0, "SPEAKER_00", "Hej."),
      segment(1, "SPEAKER_00", "Välkomna."),
      segment(2, "SPEAKER_01", "Tack."),
      segment(3, "SPEAKER_01", "Fortsatt.", { file_index: 1 })
    ]);
    const turns = transcriptTurns(
      shownSegments(lines, {
        occurrences: [],
        speaker_edits: [],
        speaker_names: { SPEAKER_00: "Anna" }
      })
    );
    expect(
      turns.map((turn) => [turn.speaker, turn.name, turn.fileIndex, turn.start, turn.parts.length])
    ).toEqual([
      ["SPEAKER_00", "Anna", 0, 0, 2],
      ["SPEAKER_01", null, 0, 10, 1],
      ["SPEAKER_01", null, 1, 15, 1]
    ]);
    expect(turns[0]!.parts.map((part) => part.position)).toEqual([0, 1]);
  });

  it("keeps a part given to another speaker in that speaker's turn, with its place in the line", () => {
    const lines = parseSegments([
      segment(0, "SPEAKER_00", "Hej på dig."),
      segment(1, "SPEAKER_01", "Tack, hej.")
    ]);
    const turns = transcriptTurns(
      shownSegments(lines, {
        occurrences: [],
        speaker_edits: [
          {
            segment_index: 0,
            char_start: 4,
            char_end: 11,
            original: "på dig.",
            original_speaker: "SPEAKER_00",
            speaker: "SPEAKER_01",
            decision: "confirmed"
          }
        ],
        speaker_names: {}
      })
    );
    expect(turns.map((turn) => [turn.speaker, turn.parts.map((part) => part.text)])).toEqual([
      ["SPEAKER_00", ["Hej "]],
      ["SPEAKER_01", ["på dig.", "Tack, hej."]]
    ]);
    expect(turns[1]!.parts[0]).toMatchObject({ segmentIndex: 0, shownStart: 4 });
  });

  it("gives a line whose speaker is unsure a turn of its own", () => {
    const lines = parseSegments([
      segment(0, "SPEAKER_00", "Ja."),
      segment(1, "SPEAKER_00", "Nej.", { speaker_attribution: "provisional" }),
      segment(2, "SPEAKER_00", "Kanske.")
    ]);
    const turns = transcriptTurns(shownSegments(lines, null));
    expect(turns.map((turn) => turn.marker)).toEqual([null, "unsure", null]);
  });
});
