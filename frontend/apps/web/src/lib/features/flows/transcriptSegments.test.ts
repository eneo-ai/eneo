import { describe, expect, it } from "vitest";

import {
  applySpeakerNames,
  attachWords,
  countFiles,
  countUncertainWords,
  findActiveSegmentIndex,
  findActiveWordIndex,
  formatClock,
  isPureTranscript,
  locateWords,
  parseTranscript,
  segmentsFromMetadata,
  speakerColorIndex,
  type TranscriptSegment
} from "./transcriptSegments";

describe("segmentsFromMetadata", () => {
  it("reads the stored segments and keeps their file index", () => {
    const segments = segmentsFromMetadata({
      segments: [
        { file_index: 0, start: 0, end: 4.5, speaker: "SPEAKER_00", text: "Hej." },
        { file_index: 1, start: 0, end: 2, speaker: null, text: "(paus)" }
      ]
    });
    expect(segments).toEqual([
      { index: 0, fileIndex: 0, start: 0, end: 4.5, speaker: "SPEAKER_00", text: "Hej." },
      { index: 1, fileIndex: 1, start: 0, end: 2, speaker: null, text: "(paus)" }
    ]);
  });

  it("returns null without segments and drops entries it cannot place in time", () => {
    expect(segmentsFromMetadata(null)).toBeNull();
    expect(segmentsFromMetadata({ segments: null })).toBeNull();
    expect(segmentsFromMetadata({ segments: [] })).toBeNull();
    expect(
      segmentsFromMetadata({
        segments: [{ start: "0", end: 1, text: "x" }, { start: 0, text: "x" }, "garbage"]
      })
    ).toBeNull();
  });
});

describe("parseTranscript", () => {
  it("parses labelled and renamed lines, ignoring lines without a timestamp", () => {
    const segments = parseTranscript(
      [
        "[00:00:00 - 00:00:04] SPEAKER_00: Hej och välkomna!",
        "Fritext utan tid.",
        "[00:01:05 - 00:01:09] Anna Svensson: Tack så mycket.",
        "[01:00:00 - 01:00:01] Utan talare",
        ""
      ].join("\n")
    );
    expect(segments).toEqual([
      {
        index: 0,
        fileIndex: 0,
        start: 0,
        end: 4,
        speaker: "SPEAKER_00",
        text: "Hej och välkomna!"
      },
      {
        index: 1,
        fileIndex: 0,
        start: 65,
        end: 69,
        speaker: "Anna Svensson",
        text: "Tack så mycket."
      },
      { index: 2, fileIndex: 0, start: 3600, end: 3601, speaker: null, text: "Utan talare" }
    ]);
  });

  it("assigns file indexes from part headers of a multi-file transcript", () => {
    const segments = parseTranscript(
      [
        "## Del 1 — kl 09:00:00",
        "",
        "[00:00:00 - 00:00:01] SPEAKER_00: Ett.",
        "",
        "## Del 2 — kl 09:10:00",
        "",
        "[00:00:00 - 00:00:01] SPEAKER_01: Två."
      ].join("\n")
    );
    expect(segments.map((segment) => segment.fileIndex)).toEqual([0, 1]);
    expect(countFiles(segments)).toBe(2);
  });
});

describe("isPureTranscript", () => {
  it("accepts timestamped lines, part headers and blank lines only", () => {
    expect(
      isPureTranscript(
        [
          "## Del 1",
          "[00:00:00 - 00:00:04] Handläggare: Hej Gunnar.",
          "",
          "[00:00:05 - 00:00:09] Gunnar: Hej."
        ].join("\n")
      )
    ).toBe(true);
  });

  it("rejects a document that merely quotes transcript lines, and empty text", () => {
    expect(
      isPureTranscript(
        ["# Samtal om hemtjänst", "", "[00:00:00 - 00:00:04] Handläggare: Hej Gunnar."].join("\n")
      )
    ).toBe(false);
    expect(isPureTranscript("")).toBe(false);
    expect(isPureTranscript("Bara text.")).toBe(false);
  });
});

describe("applySpeakerNames", () => {
  it("replaces mapped labels and leaves the rest", () => {
    const segments = parseTranscript(
      ["[00:00:00 - 00:00:01] SPEAKER_00: A.", "[00:00:02 - 00:00:03] SPEAKER_01: B."].join("\n")
    );
    const named = applySpeakerNames(segments, { SPEAKER_00: "Anna", SPEAKER_01: "  " });
    expect(named.map((segment) => segment.speaker)).toEqual(["Anna", "SPEAKER_01"]);
  });
});

describe("findActiveSegmentIndex", () => {
  const segments: TranscriptSegment[] = [
    { index: 0, fileIndex: 0, start: 0, end: 4, speaker: null, text: "" },
    { index: 1, fileIndex: 0, start: 5, end: 9, speaker: null, text: "" },
    { index: 2, fileIndex: 1, start: 0, end: 3, speaker: null, text: "" }
  ];

  it("finds the segment at a time, sticking to the previous one in gaps", () => {
    expect(findActiveSegmentIndex(segments, 0, 0)).toBe(0);
    expect(findActiveSegmentIndex(segments, 0, 4.5)).toBe(0);
    expect(findActiveSegmentIndex(segments, 0, 5)).toBe(1);
    expect(findActiveSegmentIndex(segments, 0, 7, 1)).toBe(1);
    expect(findActiveSegmentIndex(segments, 0, 2, 1)).toBe(0);
  });

  it("only matches segments of the requested file", () => {
    expect(findActiveSegmentIndex(segments, 1, 1)).toBe(2);
    expect(findActiveSegmentIndex(segments, 1, 1, 0)).toBe(2);
    expect(findActiveSegmentIndex(segments, 2, 1)).toBe(-1);
  });
});

describe("speakerColorIndex and formatClock", () => {
  it("keeps a colour per numbered label and a stable one per name", () => {
    expect(speakerColorIndex("SPEAKER_00")).toBe(0);
    expect(speakerColorIndex("SPEAKER_09")).toBe(1);
    expect(speakerColorIndex("Anna")).toBe(speakerColorIndex("Anna"));
  });

  it("formats seconds as a clock, with hours only when needed", () => {
    expect(formatClock(65)).toBe("01:05");
    expect(formatClock(3661)).toBe("01:01:01");
    expect(formatClock(65, true)).toBe("00:01:05");
  });
});

describe("attachWords and locateWords", () => {
  const segments: TranscriptSegment[] = [
    { index: 0, fileIndex: 0, start: 0, end: 4, speaker: "SPEAKER_00", text: "Hej, Çagri här." },
    { index: 1, fileIndex: 0, start: 4, end: 8, speaker: "SPEAKER_01", text: "Hallå." }
  ];

  it("places each word in the raw text and flags interpolated ones on the forced rung", () => {
    const [first, second] = attachWords(segments, {
      alignment: "forced",
      stale: false,
      segments: [
        {
          segment_index: 0,
          words: [
            { word: "Hej,", start: 0.1, end: 0.4, probability: 0.9 },
            { word: "Çagri", start: 0.5, end: 0.9, probability: 0 },
            { word: "här", start: 1.0, end: 1.3, probability: 0.8 }
          ]
        }
      ]
    });
    expect(first.words).toEqual([
      {
        word: "Hej,",
        start: 0.1,
        end: 0.4,
        probability: 0.9,
        charStart: 0,
        charEnd: 4,
        uncertain: false
      },
      {
        word: "Çagri",
        start: 0.5,
        end: 0.9,
        probability: 0,
        charStart: 5,
        charEnd: 10,
        uncertain: true
      },
      {
        word: "här",
        start: 1.0,
        end: 1.3,
        probability: 0.8,
        charStart: 11,
        charEnd: 14,
        uncertain: false
      }
    ]);
    expect(second.words).toBeUndefined();
    expect(countUncertainWords([first, second])).toBe(1);
  });

  it("retries a token bare of punctuation and keeps unlocated words unhighlighted", () => {
    const words = locateWords(
      "Vi ses imorgon.",
      [
        { word: "Vi", start: 0, end: 0.2 },
        { word: "ses,", start: 0.3, end: 0.5 },
        { word: "aldrig", start: 0.6, end: 0.8 },
        { word: "imorgon", start: 0.9, end: 1.4 }
      ],
      "forced"
    );
    expect(words.map((word) => [word.charStart, word.charEnd])).toEqual([
      [0, 2],
      [3, 6],
      [-1, -1],
      [7, 14]
    ]);
  });

  it("does not mark a zero score as uncertain outside the forced rung", () => {
    const [first] = attachWords(segments, {
      alignment: "provider_words",
      segments: [
        { segment_index: 0, words: [{ word: "Hej,", start: 0, end: 0.3, probability: 0 }] }
      ]
    });
    expect(first.words?.[0].uncertain).toBe(false);
  });

  it("ignores a stale or missing payload", () => {
    expect(attachWords(segments, null)).toEqual(segments);
    expect(attachWords(segments, { stale: true, segments: [] })[0].words).toBeUndefined();
  });
});

describe("findActiveWordIndex", () => {
  const words = locateWords(
    "a b c",
    [
      { word: "a", start: 0, end: 0.5 },
      { word: "b", start: 1, end: 1.5 },
      { word: "c", start: 2, end: 2.5 }
    ],
    null
  );

  it("finds the word at a time, sticking to the previous one in gaps", () => {
    expect(findActiveWordIndex(words, -1)).toBe(-1);
    expect(findActiveWordIndex(words, 0.7)).toBe(0);
    expect(findActiveWordIndex(words, 1.2)).toBe(1);
    expect(findActiveWordIndex(words, 1.7, 1)).toBe(1);
    expect(findActiveWordIndex(words, 9)).toBe(2);
  });
});
