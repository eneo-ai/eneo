import { describe, expect, it } from "vitest";
import { correctionSet, withLineText } from "./transcript-corrections";
import {
  changedWords,
  findOccurrences,
  suggestionsFor,
  withCasingOf,
  withSuggestions
} from "./transcript-suggestions";

const lines = [
  { index: 0, text: "Välkommen, Sugary." },
  { index: 1, text: "Tack Sugary, och tack SUGARY." },
  { index: 2, text: "Sugari hade rätt, men Sugarytown inte." },
  { index: 3, text: "Anna Lisa kom sent." }
];

describe("changedWords", () => {
  it("widens an edit to the whole words it touched", () => {
    expect(changedWords("Välkommen, Sugary.", "Välkommen, Çagri.")).toEqual({
      original: "Sugary",
      corrected: "Çagri",
      start: 11
    });
    // Removing the space between two words touches both.
    expect(changedWords("Anna Lisa kom sent.", "AnnaLisa kom sent.")).toMatchObject({
      original: "Anna Lisa",
      corrected: "AnnaLisa"
    });
  });

  it("offers nothing for a long rewrite, or for words only taken away", () => {
    expect(changedWords("ett två tre fyra fem", "sex sju åtta nio tio")).toBeNull();
    expect(changedWords("Tack Sugary.", "Tack .")).toBeNull();
    expect(changedWords("Tack.", "Tack.")).toBeNull();
  });
});

describe("findOccurrences", () => {
  it("finds whole words in any case, and close spellings, but not inside a word", () => {
    const found = findOccurrences(lines, "Sugary", { segmentIndex: 0, charStart: 11 });
    expect(found.map(({ segmentIndex, matched, kind }) => [segmentIndex, matched, kind])).toEqual([
      [1, "Sugary", "exact"],
      [1, "SUGARY", "exact"],
      [2, "Sugari", "similar"]
    ]);
  });

  it("matches several words in a row", () => {
    expect(findOccurrences(lines, "Anna Lisa", null)).toEqual([
      { segmentIndex: 3, charStart: 0, charEnd: 9, matched: "Anna Lisa", kind: "exact" }
    ]);
  });
});

describe("withCasingOf", () => {
  it("keeps the match's capitals", () => {
    expect(withCasingOf("SUGARY", "Çagri")).toBe("ÇAGRI");
    expect(withCasingOf("Sugary", "çagri")).toBe("Çagri");
    expect(withCasingOf("sugary", "Çagri")).toBe("Çagri");
  });
});

describe("suggestionsFor", () => {
  it("offers the other places, leaving out the edited one and those already corrected", () => {
    const set = correctionSet(
      {
        occurrences: [
          { segment_index: 2, char_start: 0, char_end: 6, original: "Sugari", corrected: "Sigge" }
        ],
        speaker_edits: [],
        speaker_names: {}
      },
      lines
    );
    const edited = "Välkommen, Çagri.";
    const next = withLineText(set, lines[0]!, edited);
    const offer = suggestionsFor(next, lines[0]!, edited, lines);
    expect(offer?.original).toBe("Sugary");
    expect(offer?.corrected).toBe("Çagri");
    expect(offer?.candidates.map((candidate) => candidate.matched)).toEqual(["Sugary", "SUGARY"]);

    const saved = withSuggestions(next, offer!, offer!.candidates.slice(1));
    expect(saved.occurrences).toContainEqual({
      segment_index: 1,
      char_start: 22,
      char_end: 28,
      original: "SUGARY",
      corrected: "ÇAGRI"
    });
    expect(saved.occurrences).toHaveLength(3);
  });

  it("offers nothing where nothing else matches", () => {
    const set = correctionSet(null, lines);
    const edited = "Tack Sugary, och tack SUGARY!";
    expect(
      suggestionsFor(withLineText(set, lines[1]!, edited), lines[1]!, edited, lines)
    ).toBeNull();
  });
});
