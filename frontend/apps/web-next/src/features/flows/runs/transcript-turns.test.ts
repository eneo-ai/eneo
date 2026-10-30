import { describe, expect, it } from "vitest";
import { parseSegments, shownSegments } from "./transcript";
import { correctionSet } from "./transcript-corrections";
import {
  transcriptTurns,
  turnLineTexts,
  turnText,
  withPartsSpeaker,
  withTurnText
} from "./transcript-turns";

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

describe("editing a turn as one text", () => {
  const lines = parseSegments([
    segment(0, "SPEAKER_00", "Hej på dig."),
    segment(1, "SPEAKER_00", "Hur mår du?"),
    segment(2, "SPEAKER_01", "Bra, tack.")
  ]);
  const shown = shownSegments(lines, null);
  const [turn] = transcriptTurns(shown);
  const text = (index: number) => shown[index]?.text;

  it("reads the turn's lines as one text", () => {
    expect(turnText(turn!)).toBe("Hej på dig. Hur mår du?");
  });

  it("changes only the line an edit falls in", () => {
    expect(turnLineTexts(turn!, "Hej på er. Hur mår du?", text)).toEqual(
      new Map([[0, "Hej på er."]])
    );
    expect(turnLineTexts(turn!, "Hej på dig. Hur mår ni?", text)).toEqual(
      new Map([[1, "Hur mår ni?"]])
    );
    expect(turnLineTexts(turn!, turnText(turn!), text).size).toBe(0);
  });

  it("gives an edit across lines to the first line it touches", () => {
    expect(turnLineTexts(turn!, "Hej på er, hur mår du?", text)).toEqual(
      new Map([
        [0, "Hej på er, hur"],
        [1, " mår du?"]
      ])
    );
    // Typed at the end of a line, the text joins it; after the space, the next line.
    expect(turnLineTexts(turn!, "Hej på dig, Anna. Hur mår du?", text)).toEqual(
      new Map([[0, "Hej på dig, Anna."]])
    );
    expect(turnLineTexts(turn!, "Hej på dig. Ja. Hur mår du?", text)).toEqual(
      new Map([[1, "Ja. Hur mår du?"]])
    );
  });

  it("keeps the rest of a line whose part belongs to another turn", () => {
    const split = shownSegments(lines, {
      occurrences: [],
      speaker_edits: [
        {
          segment_index: 1,
          char_start: 4,
          char_end: 11,
          original: "mår du?",
          original_speaker: "SPEAKER_00",
          speaker: "SPEAKER_01",
          decision: "confirmed"
        }
      ],
      speaker_names: {}
    });
    const second = transcriptTurns(split)[1]!;
    expect(turnText(second)).toBe("mår du? Bra, tack.");
    const { next, texts } = withTurnText(
      correctionSet(null, lines),
      second,
      "mår ni? Bra, tack.",
      new Map(split.map((line) => [line.index, line]))
    );
    expect(texts).toEqual(new Map([[1, "Hur mår ni?"]]));
    expect(next.occurrences).toEqual([
      { segment_index: 1, char_start: 8, char_end: 10, original: "du", corrected: "ni" }
    ]);
  });

  it("gives a turn's parts to another speaker and resets only the reassigned ones", () => {
    const byIndex = new Map(shown.map((line) => [line.index, line]));
    const moved = withPartsSpeaker(correctionSet(null, lines), turn!.parts, byIndex, {
      speaker: "SPEAKER_01",
      decision: "confirmed"
    });
    expect(
      moved.speakerEdits.map((edit) => [edit.segment_index, edit.char_start, edit.speaker])
    ).toEqual([
      [0, null, "SPEAKER_01"],
      [1, null, "SPEAKER_01"]
    ]);
    const after = shownSegments(lines, {
      occurrences: [],
      speaker_edits: moved.speakerEdits,
      speaker_names: {}
    });
    const reassigned = transcriptTurns(after)[0]!;
    expect(reassigned.parts.map((part) => part.overridden)).toEqual([true, true, false]);
    const reset = withPartsSpeaker(
      moved,
      reassigned.parts.slice(0, 1),
      new Map(after.map((line) => [line.index, line])),
      "reset"
    );
    expect(reset.speakerEdits.map((edit) => edit.segment_index)).toEqual([1]);
  });
});
