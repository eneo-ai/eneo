import { describe, expect, it } from "vitest";

import type { TranscriptSegment } from "./transcriptSegments";
import {
  applySpeakerEditOverlay,
  buildOffsetMap,
  computeSegmentRuns,
  nextSpeakerLabel,
  sortSpeakerEdits,
  speakerLabels,
  type SpeakerEdit
} from "./transcriptRuns";

function segment(
  index: number,
  text: string,
  speaker: string | null = "SPEAKER_00"
): TranscriptSegment {
  return { index, fileIndex: 0, start: index * 4, end: index * 4 + 4, speaker, text };
}

function edit(partial: Partial<SpeakerEdit>): SpeakerEdit {
  return {
    segment_index: 0,
    char_start: null,
    char_end: null,
    original: null,
    original_speaker: "SPEAKER_00",
    speaker: "SPEAKER_01",
    ...partial
  };
}

const LINE = "Vi frågade sugary om planen.";
const CORRECTION = {
  segment_index: 0,
  char_start: 11,
  char_end: 17,
  original: "sugary",
  corrected: "Çagri"
};

describe("buildOffsetMap", () => {
  it("is the identity without corrections", () => {
    const map = buildOffsetMap("Hej världen.", []);

    expect(map.rawToDisplay(5)).toBe(5);
    expect(map.displayToRaw(5, "start")).toBe(5);
  });

  it("shifts offsets after a replacement that changes length", () => {
    const map = buildOffsetMap("aa bb cc", [
      { segment_index: 0, char_start: 0, char_end: 2, original: "aa", corrected: "lång text" }
    ]);

    expect(map.rawToDisplay(3)).toBe(10);
    expect(map.displayToRaw(10, "start")).toBe(3);
  });

  it("clamps offsets inside a replaced span", () => {
    const map = buildOffsetMap(LINE, [{ ...CORRECTION, corrected: "XY" }]);

    // Raw offset inside "sugary" lands inside "XY", clamped to its length.
    expect(map.rawToDisplay(14)).toBe(13);
    // Display offset inside "XY" snaps to the raw span's edges by bias.
    expect(map.displayToRaw(12, "start")).toBe(11);
    expect(map.displayToRaw(12, "end")).toBe(17);
  });

  it("round-trips replacement boundaries", () => {
    const map = buildOffsetMap(LINE, [CORRECTION]);

    expect(map.rawToDisplay(11)).toBe(11);
    expect(map.rawToDisplay(17)).toBe(16);
    expect(map.displayToRaw(16, "end")).toBe(17);
    expect(map.rawToDisplay(LINE.length)).toBe(LINE.length - 1);
  });
});

describe("computeSegmentRuns", () => {
  it("yields one unowned run without edits", () => {
    expect(computeSegmentRuns("Hej.", "SPEAKER_00", [], [])).toEqual([
      {
        speaker: null,
        overridden: false,
        text: "Hej.",
        rawStart: 0,
        rawEnd: 4,
        displayStart: 0,
        displayEnd: 4
      }
    ]);
  });

  it("yields one overridden run for a whole-segment edit", () => {
    const runs = computeSegmentRuns("Hej.", "SPEAKER_00", [], [edit({})]);

    expect(runs).toHaveLength(1);
    expect(runs[0]).toMatchObject({ speaker: "SPEAKER_01", overridden: true, text: "Hej." });
  });

  it("splits a line around a mid-line span", () => {
    const runs = computeSegmentRuns(
      LINE,
      "SPEAKER_00",
      [],
      [edit({ char_start: 11, char_end: 17, original: "sugary" })]
    );

    expect(runs.map((run) => [run.speaker, run.text, run.overridden])).toEqual([
      [null, "Vi frågade ", false],
      ["SPEAKER_01", "sugary", true],
      [null, " om planen.", false]
    ]);
  });

  it("maps span boundaries through length-changing corrections", () => {
    const runs = computeSegmentRuns(
      LINE,
      "SPEAKER_00",
      [CORRECTION],
      [edit({ char_start: 18, char_end: 28, original: "om planen." })]
    );

    expect(runs.map((run) => [run.speaker, run.text])).toEqual([
      [null, "Vi frågade Çagri "],
      ["SPEAKER_01", "om planen."]
    ]);
    expect(runs[1]).toMatchObject({ rawStart: 18, rawEnd: 28, displayStart: 17, displayEnd: 27 });
  });

  it("skips edits whose speaker anchor no longer matches", () => {
    const runs = computeSegmentRuns(
      "Hej.",
      "SPEAKER_00",
      [],
      [edit({ original_speaker: "SPEAKER_05" })]
    );

    expect(runs).toEqual([expect.objectContaining({ speaker: null, overridden: false })]);
  });

  it("skips edits whose span text no longer matches", () => {
    const runs = computeSegmentRuns(
      "Hej världen.",
      "SPEAKER_00",
      [],
      [edit({ char_start: 0, char_end: 3, original: "Nej" })]
    );

    expect(runs).toEqual([expect.objectContaining({ speaker: null, overridden: false })]);
  });
});

describe("applySpeakerEditOverlay", () => {
  const segments = [segment(0, "abcdefgh"), segment(1, LINE, "SPEAKER_01")];

  it("fills anchors from the raw segments for a new span", () => {
    const merged = applySpeakerEditOverlay(
      [],
      [{ segment_index: 1, char_start: 11, char_end: 17, speaker: "SPEAKER_02" }],
      segments
    );

    expect(merged).toEqual([
      {
        segment_index: 1,
        char_start: 11,
        char_end: 17,
        original: "sugary",
        original_speaker: "SPEAKER_01",
        speaker: "SPEAKER_02"
      }
    ]);
  });

  it("serializes full coverage as one whole-segment edit", () => {
    const merged = applySpeakerEditOverlay(
      [],
      [{ segment_index: 0, char_start: 0, char_end: 8, speaker: "SPEAKER_01" }],
      segments
    );

    expect(merged).toEqual([
      {
        segment_index: 0,
        char_start: null,
        char_end: null,
        original: null,
        original_speaker: "SPEAKER_00",
        speaker: "SPEAKER_01"
      }
    ]);
  });

  it("lets the newest reassignment win where spans overlap", () => {
    const existing = [
      edit({ char_start: 0, char_end: 4, original: "abcd", speaker: "SPEAKER_01" })
    ];

    const merged = applySpeakerEditOverlay(
      existing,
      [{ segment_index: 0, char_start: 2, char_end: 6, speaker: "SPEAKER_02" }],
      segments
    );

    expect(merged.map((item) => [item.char_start, item.char_end, item.speaker])).toEqual([
      [0, 2, "SPEAKER_01"],
      [2, 6, "SPEAKER_02"]
    ]);
    expect(merged[0].original).toBe("ab");
  });

  it("drops an edit when content is reassigned back to the stored speaker", () => {
    const merged = applySpeakerEditOverlay(
      [edit({})],
      [{ segment_index: 0, char_start: null, char_end: null, speaker: "SPEAKER_00" }],
      segments
    );

    expect(merged).toEqual([]);
  });

  it("absorbs trailing punctuation into the reassigned span", () => {
    const merged = applySpeakerEditOverlay(
      [],
      [{ segment_index: 0, char_start: 0, char_end: 12, speaker: "SPEAKER_01" }],
      [segment(0, "Detta är bra.")]
    );

    // The lone "." never stays behind on the original speaker.
    expect(merged).toEqual([
      expect.objectContaining({ char_start: null, char_end: null, speaker: "SPEAKER_01" })
    ]);
  });

  it("absorbs leading punctuation into the following span", () => {
    const merged = applySpeakerEditOverlay(
      [],
      [{ segment_index: 0, char_start: 2, char_end: 12, speaker: "SPEAKER_01" }],
      [segment(0, "– Ja precis.")]
    );

    expect(merged).toEqual([
      expect.objectContaining({ char_start: null, char_end: null, speaker: "SPEAKER_01" })
    ]);
  });

  it("keeps sentence punctuation with the sentence that moved", () => {
    const merged = applySpeakerEditOverlay(
      [],
      [{ segment_index: 0, char_start: 9, char_end: 16, speaker: "SPEAKER_01" }],
      [segment(0, "Hej där. Vad bra.")]
    );

    expect(merged).toEqual([
      {
        segment_index: 0,
        char_start: 9,
        char_end: 17,
        original: "Vad bra.",
        original_speaker: "SPEAKER_00",
        speaker: "SPEAKER_01"
      }
    ]);
  });

  it("merges adjacent same-speaker spans into a whole-segment edit", () => {
    const merged = applySpeakerEditOverlay(
      [],
      [
        { segment_index: 0, char_start: 0, char_end: 4, speaker: "SPEAKER_01" },
        { segment_index: 0, char_start: 4, char_end: 8, speaker: "SPEAKER_01" }
      ],
      segments
    );

    expect(merged).toEqual([
      expect.objectContaining({ char_start: null, char_end: null, speaker: "SPEAKER_01" })
    ]);
  });
});

describe("speakerLabels", () => {
  it("keeps first-appearance order and includes edit-introduced labels", () => {
    const segments = [segment(0, "a"), segment(1, "b", "SPEAKER_01"), segment(2, "c")];

    expect(speakerLabels(segments, [edit({ speaker: "SPEAKER_03" })])).toEqual([
      "SPEAKER_00",
      "SPEAKER_01",
      "SPEAKER_03"
    ]);
  });
});

describe("nextSpeakerLabel", () => {
  it("mints the next unused numeric label", () => {
    expect(nextSpeakerLabel(["SPEAKER_00", "SPEAKER_03"])).toBe("SPEAKER_04");
    expect(nextSpeakerLabel([])).toBe("SPEAKER_00");
  });
});

describe("sortSpeakerEdits", () => {
  it("orders whole-segment edits before spans within a segment", () => {
    const span = edit({ char_start: 0, char_end: 2, original: "ab" });
    const whole = edit({});
    const later = edit({ segment_index: 1, original_speaker: "SPEAKER_01" });

    expect(sortSpeakerEdits([later, span, whole])).toEqual([whole, span, later]);
  });
});
