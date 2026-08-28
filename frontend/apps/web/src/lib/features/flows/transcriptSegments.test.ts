import { describe, expect, it } from "vitest";

import {
  applySpeakerNames,
  countFiles,
  findActiveSegmentIndex,
  formatClock,
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
