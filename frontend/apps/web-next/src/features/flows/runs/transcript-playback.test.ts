import { describe, expect, it } from "vitest";
import type { TranscriptSegment } from "./transcript";
import {
  activeLine,
  activeWord,
  captionsFor,
  placeWords,
  textRuns,
  wordsByLine,
  type TranscriptWords
} from "./transcript-playback";

const line = (
  index: number,
  fileIndex: number,
  start: number,
  text: string
): TranscriptSegment => ({
  index,
  fileIndex,
  start,
  end: start + 3,
  speaker: "SPEAKER_00",
  text
});

const lines = [
  line(0, 0, 0, "Välkomna, alla."),
  line(1, 0, 4, "Vi börjar."),
  line(2, 1, 0, "Del två.")
];

function payload(overrides: Partial<TranscriptWords> = {}): TranscriptWords {
  return {
    alignment: "forced",
    created_at: "2026-10-21T09:00:00Z",
    flow_run_id: "run-1",
    step_id: "step-1",
    segments_hash: "hash-1",
    stale: false,
    segments: [
      {
        segment_index: 0,
        words: [
          { word: "Välkomna,", start: 0.1, end: 0.8, probability: 0.9 },
          { word: "alla", start: 0.9, end: 1.3, probability: 0 }
        ]
      }
    ],
    ...overrides
  } as TranscriptWords;
}

describe("placeWords", () => {
  it("places each word in the text, also without the punctuation the aligner kept", () => {
    const placed = placeWords(
      "Välkomna, alla.",
      [
        { word: "Välkomna,", start: 0, end: 1 },
        { word: "alla.!", start: 1, end: 2 },
        { word: "saknas", start: 2, end: 3 }
      ],
      "provider_words"
    );
    expect(placed.map((word) => [word.charStart, word.charEnd])).toEqual([
      [0, 9],
      [10, 14],
      [-1, -1]
    ]);
  });

  it("marks words the forced aligner spread over their window", () => {
    const placed = placeWords("a b", [{ word: "a", start: 0, end: 1, probability: 0 }], "forced");
    expect(placed[0]!.uncertain).toBe(true);
  });
});

describe("wordsByLine", () => {
  it("uses words written for this transcript only", () => {
    expect(wordsByLine(lines, payload(), "hash-1").get(0)).toHaveLength(2);
    expect(wordsByLine(lines, payload({ stale: true }), "hash-1").size).toBe(0);
    expect(wordsByLine(lines, payload(), "hash-2").size).toBe(0);
    expect(wordsByLine(lines, null, "hash-1").size).toBe(0);
  });
});

describe("activeLine and activeWord", () => {
  it("finds the line playing in a file, keeping the earlier line between two", () => {
    expect(activeLine(lines, 0, 2)).toBe(0);
    expect(activeLine(lines, 0, 3.5)).toBe(0);
    expect(activeLine(lines, 0, 4)).toBe(1);
    expect(activeLine(lines, 1, 0.5)).toBe(2);
    expect(activeLine(lines, 1, -1)).toBe(-1);
  });

  it("finds the word playing", () => {
    const words = [{ start: 0.1 }, { start: 0.9 }];
    expect(activeWord(words, 0)).toBe(-1);
    expect(activeWord(words, 0.5)).toBe(0);
    expect(activeWord(words, 5)).toBe(1);
  });
});

describe("textRuns", () => {
  it("cuts a line at its placed words and keeps the text between them", () => {
    const placed = wordsByLine(lines, payload(), "hash-1").get(0)!;
    expect(textRuns("Välkomna, alla.", placed)).toEqual([
      { text: "Välkomna,", word: 0 },
      { text: " ", word: null },
      { text: "alla", word: 1 },
      { text: ".", word: null }
    ]);
  });
});

describe("captionsFor", () => {
  it("writes one file's lines as WebVTT cues with the speaker as voice", () => {
    expect(captionsFor(lines, 0, (position) => (position === 0 ? "Anna" : "Bo"))).toBe(
      "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\n<v Anna>Välkomna, alla.\n\n" +
        "00:00:04.000 --> 00:00:07.000\n<v Bo>Vi börjar.\n"
    );
  });
});
