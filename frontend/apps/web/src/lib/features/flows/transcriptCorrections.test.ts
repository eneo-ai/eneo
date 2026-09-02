import { describe, expect, it } from "vitest";

import type { TranscriptSegment } from "./transcriptSegments";
import {
  applyCasingPattern,
  applyTextCorrections,
  boundedEditDistance,
  diffLineEdit,
  findOccurrences,
  sortOccurrences,
  splitWords,
  type CorrectionOccurrence
} from "./transcriptCorrections";

function segment(index: number, text: string): TranscriptSegment {
  return { index, fileIndex: 0, start: index * 4, end: index * 4 + 4, speaker: "SPEAKER_00", text };
}

function occurrence(partial: Partial<CorrectionOccurrence>): CorrectionOccurrence {
  return {
    segment_index: 0,
    char_start: 0,
    char_end: 1,
    original: "",
    corrected: "",
    ...partial
  };
}

describe("applyTextCorrections", () => {
  it("applies multiple corrections on one line without shifting offsets", () => {
    const segments = [segment(0, "sugary pratade med sugary igår.")];
    const applied = applyTextCorrections(segments, [
      occurrence({ char_start: 0, char_end: 6, original: "sugary", corrected: "Çagri" }),
      occurrence({ char_start: 19, char_end: 25, original: "sugary", corrected: "Çagri" })
    ]);

    expect(applied.segments[0].text).toBe("Çagri pratade med Çagri igår.");
    expect(applied.correctedFrom.get(0)).toBe("sugary pratade med sugary igår.");
    expect(applied.skipped).toBe(0);
  });

  it("skips occurrences whose anchor no longer matches", () => {
    const segments = [segment(0, "Hej världen.")];
    const applied = applyTextCorrections(segments, [
      occurrence({ char_start: 0, char_end: 3, original: "Nej", corrected: "Tja" })
    ]);

    expect(applied.segments[0].text).toBe("Hej världen.");
    expect(applied.correctedFrom.size).toBe(0);
    expect(applied.skipped).toBe(1);
  });

  it("leaves untouched lines and non-text fields alone", () => {
    const segments = [segment(0, "Hej."), segment(1, "Då.")];
    const applied = applyTextCorrections(segments, [
      occurrence({ segment_index: 1, char_start: 0, char_end: 2, original: "Då", corrected: "Nu" })
    ]);

    expect(applied.segments[0]).toBe(segments[0]);
    expect(applied.segments[1].text).toBe("Nu.");
    expect(applied.segments[1].speaker).toBe("SPEAKER_00");
  });
});

describe("diffLineEdit", () => {
  it("returns null for an unchanged line", () => {
    expect(diffLineEdit("Hej.", "Hej.")).toEqual({ occurrence: null, tokenShaped: null });
  });

  it("trims to the minimal changed span", () => {
    const diff = diffLineEdit("Vi frågade sugary om planen.", "Vi frågade Çagri om planen.");

    expect(diff.occurrence).toEqual({
      char_start: 11,
      char_end: 17,
      original: "sugary",
      corrected: "Çagri"
    });
    expect(diff.tokenShaped).toEqual({ originalText: "sugary", correctedText: "Çagri" });
  });

  it("expands a mid-word edit to the whole token", () => {
    const diff = diffLineEdit("Hon hette Chagri.", "Hon hette Çagri.");

    // The minimal diff is a single character; the token region is the word.
    expect(diff.tokenShaped).toEqual({ originalText: "Chagri", correctedText: "Çagri" });
  });

  it("handles a multi-word name split across tokens", () => {
    const diff = diffLineEdit("Vi mötte Anna Lisa idag.", "Vi mötte Annalisa idag.");

    expect(diff.tokenShaped).toEqual({ originalText: "Anna Lisa", correctedText: "Annalisa" });
  });

  it("anchors a mid-line insertion to the following character", () => {
    const diff = diffLineEdit("Vi ses imorgon.", "Vi ses nog imorgon.");

    // A pure insertion has no raw span of its own; the occurrence must
    // address at least one raw character to be a valid replacement.
    expect(diff.occurrence).toEqual({
      char_start: 7,
      char_end: 8,
      original: "i",
      corrected: "nog i"
    });
  });

  it("anchors an insertion at the start of the line", () => {
    const diff = diffLineEdit("kommer du?", "Men kommer du?");

    expect(diff.occurrence).toEqual({
      char_start: 0,
      char_end: 1,
      original: "k",
      corrected: "Men k"
    });
  });

  it("anchors an insertion at the end of the line", () => {
    const diff = diffLineEdit("Det blir bra", "Det blir bra, tror jag");

    expect(diff.occurrence).toEqual({
      char_start: 11,
      char_end: 12,
      original: "a",
      corrected: "a, tror jag"
    });
  });

  it("returns no occurrence when inserting into an empty line", () => {
    expect(diffLineEdit("", "Hej.")).toEqual({ occurrence: null, tokenShaped: null });
  });

  it("does not treat a rewritten line as token-shaped", () => {
    const diff = diffLineEdit(
      "Detta är en helt vanlig mening med många ord.",
      "Nu står det något fullständigt annat på raden istället."
    );

    expect(diff.occurrence).not.toBeNull();
    expect(diff.tokenShaped).toBeNull();
  });

  it("keeps offsets character-based for non-ASCII text", () => {
    const diff = diffLineEdit("Çagri sa hej.", "Çagri sa nej.");

    expect(diff.occurrence).toEqual({
      char_start: 9,
      char_end: 10,
      original: "h",
      corrected: "n"
    });
  });
});

describe("splitWords", () => {
  it("strips surrounding punctuation but keeps offsets into the raw text", () => {
    const words = splitWords('Han sa: "sugary!" (igen).');

    expect(words.map((span) => span.word)).toEqual(["Han", "sa", "sugary", "igen"]);
    expect(words[2].offset).toBe(9);
  });

  it("keeps non-ASCII letters and inner hyphens/apostrophes", () => {
    const words = splitWords("Çagri-Ö'Brien kom.");

    expect(words[0].word).toBe("Çagri-Ö'Brien");
  });
});

describe("boundedEditDistance", () => {
  it("computes small distances and cuts off above the limit", () => {
    expect(boundedEditDistance("chagri", "shagri", 2)).toBe(1);
    expect(boundedEditDistance("chagri", "sugary", 2)).toBeGreaterThan(2);
  });
});

describe("findOccurrences", () => {
  const segments = [
    segment(0, "Vi frågade sugary om planen."),
    segment(1, "Sugary svarade direkt, sa Shagri."),
    segment(2, "Chagrin är något helt annat."),
    segment(3, "Efterrätten var sugary, sött värre.")
  ];

  it("finds exact whole-token matches case-insensitively", () => {
    const candidates = findOccurrences(segments, "sugary", null);
    const exact = candidates.filter((candidate) => candidate.kind === "exact");

    expect(exact.map((candidate) => [candidate.segmentIndex, candidate.matchedText])).toEqual([
      [0, "sugary"],
      [1, "Sugary"],
      [3, "sugary"]
    ]);
  });

  it("never matches inside a longer token", () => {
    const candidates = findOccurrences(segments, "Chagri", null);

    // "Chagrin" is a different token; at most a fuzzy candidate, never a
    // substring hit that would corrupt it into "Çagrin".
    const chagrin = candidates.find((candidate) => candidate.segmentIndex === 2);
    expect(chagrin?.kind).not.toBe("exact");
    expect(chagrin?.matchedText).toBe("Chagrin");
  });

  it("finds fuzzy candidates for a different mangling of the name", () => {
    const candidates = findOccurrences(segments, "Chagri", null);

    const shagri = candidates.find((candidate) => candidate.matchedText === "Shagri");
    expect(shagri?.kind).toBe("fuzzy");
  });

  it("excludes the span the user already corrected", () => {
    const candidates = findOccurrences(segments, "sugary", { segmentIndex: 0, charStart: 11 });

    expect(
      candidates.some((candidate) => candidate.segmentIndex === 0 && candidate.charStart === 11)
    ).toBe(false);
  });

  it("matches multi-word originals against joined consecutive tokens", () => {
    const multi = [segment(0, "Anna Lisa kom sent. Vi frågade Anna Lisa varför.")];
    const candidates = findOccurrences(multi, "Anna Lisa", { segmentIndex: 0, charStart: 0 });

    expect(candidates).toHaveLength(1);
    expect(candidates[0].matchedText).toBe("Anna Lisa");
    expect(candidates[0].charStart).toBe(31);
  });
});

describe("applyCasingPattern", () => {
  it("carries capitalization and all-caps over to the replacement", () => {
    expect(applyCasingPattern("Sugary", "çagri")).toBe("Çagri");
    expect(applyCasingPattern("SUGARY", "çagri")).toBe("ÇAGRI");
    expect(applyCasingPattern("sugary", "çagri")).toBe("çagri");
  });
});

describe("sortOccurrences", () => {
  it("orders by segment then char_start", () => {
    const late = occurrence({ segment_index: 1, char_start: 0 });
    const earlySecond = occurrence({ segment_index: 0, char_start: 9 });
    const earlyFirst = occurrence({ segment_index: 0, char_start: 2 });

    expect(sortOccurrences([late, earlySecond, earlyFirst])).toEqual([
      earlyFirst,
      earlySecond,
      late
    ]);
  });
});
