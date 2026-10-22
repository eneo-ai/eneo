import { describe, expect, it } from "vitest";
import {
  correctedText,
  correctionSet,
  diffLineEdit,
  editRequest,
  withLineText,
  withoutLineText
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
