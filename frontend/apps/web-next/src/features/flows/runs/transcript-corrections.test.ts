import { describe, expect, it } from "vitest";
import {
  correctedText,
  correctionSet,
  diffLineEdit,
  editRequest,
  knownSpeakers,
  lineParts,
  nextSpeakerLabel,
  shownToRaw,
  withLineText,
  withoutLineText,
  withSpeaker
} from "./transcript-corrections";

const lines = [
  { index: 0, text: "Välkomna till sugary mötet." },
  { index: 1, text: "🎉 Fest för Çagri" }
];

describe("diffLineEdit", () => {
  it("replaces only what changed", () => {
    expect(diffLineEdit("Välkomna till sugary mötet.", "Välkomna till Çagri mötet.")).toEqual({
      char_start: 14,
      char_end: 20,
      original: "sugary",
      corrected: "Çagri"
    });
  });

  it("takes a neighbouring character along for a pure insertion, and refuses an empty line", () => {
    expect(diffLineEdit("Hej alla", "Hej på alla")).toEqual({
      char_start: 4,
      char_end: 5,
      original: "a",
      corrected: "på a"
    });
    expect(diffLineEdit("", "Ny text")).toBeNull();
    expect(diffLineEdit("Samma", "Samma")).toBeNull();
  });
});

describe("correction sets", () => {
  it("reads the core's code-point offsets as text offsets, and writes them back", () => {
    // "Çagri" starts at code point 11, but at UTF-16 offset 12 after the emoji.
    const set = correctionSet(
      {
        occurrences: [
          { segment_index: 1, char_start: 11, char_end: 16, original: "Çagri", corrected: "Chagri" }
        ],
        speaker_edits: [],
        speaker_names: { SPEAKER_00: "Anna" }
      },
      lines
    );
    expect(set.occurrences[0]).toMatchObject({ char_start: 12, char_end: 17 });
    expect(correctedText(lines[1]!.text, set.occurrences)).toBe("🎉 Fest för Chagri");

    const body = editRequest({ revision: 4, segments_hash: "hash-1" }, set, lines, "hash-x");
    expect(body).toEqual({
      expected_revision: 4,
      segments_hash: "hash-1",
      schema_version: 3,
      occurrences: [
        { segment_index: 1, char_start: 11, char_end: 16, original: "Çagri", corrected: "Chagri" }
      ],
      speaker_edits: [],
      speaker_names: { SPEAKER_00: "Anna" }
    });
  });

  it("corrects a line by its raw text and keeps the other lines' corrections", () => {
    const saved = correctionSet(
      {
        occurrences: [
          { segment_index: 1, char_start: 11, char_end: 16, original: "Çagri", corrected: "Chagri" }
        ],
        speaker_edits: [],
        speaker_names: {}
      },
      lines
    );
    const next = withLineText(saved, lines[0]!, "Välkomna till Çagri mötet.");
    expect(next.occurrences.map((occurrence) => occurrence.segment_index)).toEqual([1, 0]);
    expect(correctedText(lines[0]!.text, next.occurrences)).toBe("Välkomna till Çagri mötet.");
    // Back to the raw text: the line's corrections go.
    expect(withLineText(next, lines[0]!, lines[0]!.text).occurrences).toHaveLength(1);
    expect(withoutLineText(next, 1).occurrences.map((item) => item.segment_index)).toEqual([0]);
  });

  it("leaves out a correction whose anchor no longer matches its line", () => {
    expect(
      correctedText("Annan text", [
        { segment_index: 0, char_start: 0, char_end: 4, original: "Hej!", corrected: "Hallå" }
      ])
    ).toBe("Annan text");
  });

  it("starts a first set without a revision, against the source's hash", () => {
    const body = editRequest(null, correctionSet(null, lines), lines, "hash-x");
    expect(body).toMatchObject({ expected_revision: null, segments_hash: "hash-x" });
  });
});

describe("speaker edits", () => {
  const line = { index: 0, text: "Ja. Nej, inte alls.", speaker: "SPEAKER_00" };
  const empty = correctionSet(null, [line]);

  it("gives the whole line to another speaker, confirmed or unsure", () => {
    const set = withSpeaker(empty, line, null, { speaker: "SPEAKER_01", decision: "unresolved" });
    expect(set.speakerEdits).toEqual([
      {
        segment_index: 0,
        char_start: null,
        char_end: null,
        original: null,
        original_speaker: "SPEAKER_00",
        speaker: "SPEAKER_01",
        decision: "unresolved"
      }
    ]);
    expect(lineParts(line.text, line.speaker, [], set.speakerEdits)).toMatchObject([
      { speaker: "SPEAKER_01", decision: "unresolved", text: line.text }
    ]);
  });

  it("splits a line at a span and joins punctuation to its neighbour", () => {
    const set = withSpeaker(
      empty,
      line,
      { start: 3, end: 19 },
      {
        speaker: "SPEAKER_01",
        decision: "confirmed"
      }
    );
    expect(set.speakerEdits).toEqual([
      {
        segment_index: 0,
        char_start: 3,
        char_end: 19,
        original: " Nej, inte alls.",
        original_speaker: "SPEAKER_00",
        speaker: "SPEAKER_01",
        decision: "confirmed"
      }
    ]);
    expect(
      lineParts(line.text, line.speaker, [], set.speakerEdits).map((part) => [
        part.speaker,
        part.text
      ])
    ).toEqual([
      ["SPEAKER_00", "Ja."],
      ["SPEAKER_01", " Nej, inte alls."]
    ]);
    // Restoring the line takes every edit of it away.
    expect(withSpeaker(set, line, null, "reset").speakerEdits).toEqual([]);
  });

  it("maps a mark in the corrected text back to the raw text", () => {
    const occurrences = [
      { segment_index: 0, char_start: 0, char_end: 3, original: "Ja.", corrected: "Jajamän." }
    ];
    // "Jajamän. Nej, inte alls.": the mark after the replacement starts at raw offset 3.
    expect(shownToRaw(line.text, occurrences, 8, "start")).toBe(3);
    expect(shownToRaw(line.text, occurrences, 2, "start")).toBe(0);
    expect(shownToRaw(line.text, occurrences, 2, "end")).toBe(3);
  });

  it("names a new speaker after the highest label", () => {
    expect(
      nextSpeakerLabel(knownSpeakers([{ speaker: "SPEAKER_00" }], [{ speaker: "SPEAKER_03" }]))
    ).toBe("SPEAKER_04");
    expect(nextSpeakerLabel([])).toBe("SPEAKER_00");
  });
});
