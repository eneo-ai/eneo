import { describe, expect, it } from "vitest";

import type { TranscriptSegment } from "./transcriptSegments";
import {
  computeTurns,
  correctedDisplayRanges,
  splitTurnEdit,
  turnEditableText,
  turnSelectionToDisplaySpans,
  type TranscriptTurn
} from "./transcriptTurns";
import type { SpeakerEdit } from "./transcriptRuns";

function segment(
  index: number,
  text: string,
  speaker: string | null = "SPEAKER_00",
  fileIndex = 0
): TranscriptSegment {
  return { index, fileIndex, start: index * 4, end: index * 4 + 4, speaker, text };
}

function wholeEdit(segmentIndex: number, from: string, to: string): SpeakerEdit {
  return {
    segment_index: segmentIndex,
    char_start: null,
    char_end: null,
    original: null,
    original_speaker: from,
    speaker: to
  };
}

describe("computeTurns", () => {
  it("merges consecutive same-speaker segments into one turn", () => {
    const segments = [
      segment(0, "Innan vi går in på varför."),
      segment(1, "Vi satt lite och snackade."),
      segment(2, "Expressens, Brottscentralen.", "SPEAKER_01")
    ];

    const turns = computeTurns(segments, [], []);

    expect(turns.map((turn) => [turn.speaker, turn.parts.length])).toEqual([
      ["SPEAKER_00", 2],
      ["SPEAKER_01", 1]
    ]);
    expect(turns[0].start).toBe(0);
    expect(turns[0].parts.map((part) => part.segmentIndex)).toEqual([0, 1]);
  });

  it("re-flows a reassigned fragment into the neighboring speaker's turn", () => {
    const segments = [
      segment(0, "Det"),
      segment(1, "är inte helt lätt med allt det där.", "SPEAKER_01")
    ];

    const turns = computeTurns(segments, [], [wholeEdit(0, "SPEAKER_00", "SPEAKER_01")]);

    expect(turns).toHaveLength(1);
    expect(turns[0].speaker).toBe("SPEAKER_01");
    expect(turns[0].parts.map((part) => part.text)).toEqual([
      "Det",
      "är inte helt lätt med allt det där."
    ]);
    expect(turns[0].parts[0].overridden).toBe(true);
  });

  it("splits a segment across turns when a span is reassigned", () => {
    const segments = [segment(0, "Hej där. Vad bra."), segment(1, "Precis så.", "SPEAKER_01")];
    const spanEdit: SpeakerEdit = {
      segment_index: 0,
      char_start: 9,
      char_end: 17,
      original: "Vad bra.",
      original_speaker: "SPEAKER_00",
      speaker: "SPEAKER_01"
    };

    const turns = computeTurns(segments, [], [spanEdit]);

    expect(turns.map((turn) => [turn.speaker, turn.parts.map((part) => part.text)])).toEqual([
      ["SPEAKER_00", ["Hej där. "]],
      ["SPEAKER_01", ["Vad bra.", "Precis så."]]
    ]);
    expect(turns[1].parts[0]).toMatchObject({ segmentIndex: 0, rawStart: 9, rawEnd: 17 });
  });

  it("breaks turns at file boundaries even for the same speaker", () => {
    const segments = [segment(0, "Del ett."), segment(1, "Del två.", "SPEAKER_00", 1)];

    const turns = computeTurns(segments, [], []);

    expect(turns).toHaveLength(2);
    expect(turns.map((turn) => turn.fileIndex)).toEqual([0, 1]);
  });

  it("carries corrected ranges into parts, clipped to the part", () => {
    const segments = [segment(0, "Vi frågade sugary om planen.")];
    const corrections = [
      { segment_index: 0, char_start: 11, char_end: 17, original: "sugary", corrected: "Çagri" }
    ];

    const turns = computeTurns(segments, corrections, []);

    expect(turns[0].parts[0].text).toBe("Vi frågade Çagri om planen.");
    expect(turns[0].parts[0].correctedRanges).toEqual([{ start: 11, end: 16 }]);
  });
});

describe("correctedDisplayRanges", () => {
  it("marks only replaced spans, shifted into display space", () => {
    const raw = "aa bb cc";
    const ranges = correctedDisplayRanges(raw, [
      { segment_index: 0, char_start: 0, char_end: 2, original: "aa", corrected: "lång" },
      { segment_index: 0, char_start: 6, char_end: 8, original: "cc", corrected: "x" }
    ]);

    expect(ranges).toEqual([
      { start: 0, end: 4 },
      { start: 8, end: 9 }
    ]);
  });

  it("skips pure deletions", () => {
    expect(
      correctedDisplayRanges("Hej alltså.", [
        { segment_index: 0, char_start: 3, char_end: 10, original: " alltså", corrected: "" }
      ])
    ).toEqual([]);
  });
});

function twoPartTurn(): TranscriptTurn {
  const segments = [segment(0, "Hej där."), segment(1, "Vad bra.")];
  return computeTurns(segments, [], [])[0];
}

describe("turn editing", () => {
  it("joins part texts with single spaces", () => {
    expect(turnEditableText(twoPartTurn())).toBe("Hej där. Vad bra.");
  });

  it("routes an edit inside one part to that segment only", () => {
    const edits = splitTurnEdit(twoPartTurn(), "Hej där. Vad fint.", (index) =>
      index === 0 ? "Hej där." : "Vad bra."
    );

    expect(edits).toEqual([{ segmentIndex: 1, newSegmentText: "Vad fint." }]);
  });

  it("routes an edit in the first part to the first segment", () => {
    const edits = splitTurnEdit(twoPartTurn(), "Hej du. Vad bra.", (index) =>
      index === 0 ? "Hej där." : "Vad bra."
    );

    expect(edits).toEqual([{ segmentIndex: 0, newSegmentText: "Hej du." }]);
  });

  it("keeps the concatenation exact when an edit crosses the seam", () => {
    const edits = splitTurnEdit(twoPartTurn(), "Hej förresten bra.", (index) =>
      index === 0 ? "Hej där." : "Vad bra."
    );

    expect(edits).toEqual([
      { segmentIndex: 0, newSegmentText: "Hej förresten" },
      { segmentIndex: 1, newSegmentText: "bra." }
    ]);
  });

  it("stitches a partial-segment part back into its full segment text", () => {
    const segments = [segment(0, "Hej där. Vad bra."), segment(1, "Precis så.", "SPEAKER_01")];
    const spanEdit: SpeakerEdit = {
      segment_index: 0,
      char_start: 9,
      char_end: 17,
      original: "Vad bra.",
      original_speaker: "SPEAKER_00",
      speaker: "SPEAKER_01"
    };
    const turn = computeTurns(segments, [], [spanEdit])[1];

    const edits = splitTurnEdit(turn, "Vad fint. Precis så.", (index) =>
      index === 0 ? "Hej där. Vad bra." : "Precis så."
    );

    expect(edits).toEqual([{ segmentIndex: 0, newSegmentText: "Hej där. Vad fint." }]);
  });

  it("returns nothing for an unchanged turn", () => {
    expect(splitTurnEdit(twoPartTurn(), "Hej där. Vad bra.", () => "")).toEqual([]);
  });
});

describe("turnSelectionToDisplaySpans", () => {
  it("maps joined offsets onto per-segment display spans", () => {
    const spans = turnSelectionToDisplaySpans(twoPartTurn(), 4, 13);

    expect(spans).toEqual([
      { segmentIndex: 0, displayStart: 4, displayEnd: 8 },
      { segmentIndex: 1, displayStart: 0, displayEnd: 4 }
    ]);
  });

  it("skips parts outside the selection", () => {
    expect(turnSelectionToDisplaySpans(twoPartTurn(), 9, 12)).toEqual([
      { segmentIndex: 1, displayStart: 0, displayEnd: 3 }
    ]);
  });
});
