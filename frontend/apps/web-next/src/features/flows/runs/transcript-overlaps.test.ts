import { describe, expect, it } from "vitest";
import { overlapDetectionUnavailable, overlaps } from "./transcript-overlaps";

const review = {
  files: [
    {
      file_index: 0,
      overlap_detection: "available",
      overlaps: [
        { id: "f1:o2", start: 30, end: 33, detected_speaker_count: 3 },
        { id: "f1:o1", start: 10, end: 12, detected_speaker_count: 2 },
        { id: "", start: 1, end: 2 },
        { id: "f1:o3", start: 5, end: 5 }
      ]
    }
  ]
};

describe("overlaps", () => {
  it("lists the review's overlaps in time with their lines and how many are still open", () => {
    const shown = [
      { overlapIds: ["f1:o1"], unsure: true },
      { overlapIds: ["f1:o1"], unsure: false },
      { unsure: false },
      { overlapIds: ["f1:o2"], unsure: false }
    ];
    expect(overlaps(review, shown)).toEqual([
      { id: "f1:o1", fileIndex: 0, start: 10, end: 12, voices: 2, lines: [0, 1], open: 1 },
      { id: "f1:o2", fileIndex: 0, start: 30, end: 33, voices: 3, lines: [3], open: 0 }
    ]);
    expect(overlaps(null, shown)).toEqual([]);
  });

  it("says when the speaker service could not look for overlaps", () => {
    expect(overlapDetectionUnavailable(review)).toBe(false);
    expect(
      overlapDetectionUnavailable({ files: [{ file_index: 0, overlap_detection: "unavailable" }] })
    ).toBe(true);
  });
});
