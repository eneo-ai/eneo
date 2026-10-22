import { describe, expect, it } from "vitest";
import {
  leftOutSources,
  reasonSlug,
  segmentCounts,
  segmentRanges,
  type LongMaterialCoverage
} from "./long-material";

function makeCoverage(overrides: Partial<LongMaterialCoverage> = {}): LongMaterialCoverage {
  return {
    mode: "digest",
    coverage: "partial",
    reasons: ["deadline"],
    left_out: ["S2"],
    sources: [
      {
        key: "S1",
        index: 1,
        title: "Avtal.pdf",
        reference: { kind: "file" },
        start_char: 0,
        end_char: 100,
        segments_planned: 2,
        segments_read: [1, 2],
        complete: true
      },
      {
        key: "S2",
        index: 2,
        title: "Bilaga.pdf",
        reference: { kind: "file" },
        start_char: 100,
        end_char: 400,
        segments_planned: 6,
        segments_read: [1, 2],
        segments_failed: [3],
        segments_not_read: [4, 5, 6],
        complete: false
      }
    ],
    input_tokens_estimate: 90_000,
    segment_tokens: 12_000,
    reduce_input_tokens: 60_000,
    reduce_levels: 1,
    map_calls: 5,
    reduce_calls: 1,
    failed_calls: 1,
    ...overrides
  };
}

describe("long material coverage", () => {
  it("writes segments as ranges", () => {
    expect(segmentRanges([5, 1, 2, 3, 3])).toBe("1-3, 5");
    expect(segmentRanges([])).toBe("");
  });

  it("names the sources left out and the segments missing from each", () => {
    expect(leftOutSources(makeCoverage())).toEqual([
      { key: "S2", title: "Bilaga.pdf", segments: "3-6", planned: 6 }
    ]);
    expect(segmentCounts(makeCoverage())).toEqual({ read: 4, planned: 8 });
  });

  it("says a source read in full was left out at the answer", () => {
    const coverage = makeCoverage({
      sources: [{ ...makeCoverage().sources[0]!, complete: false, excluded_at_reduce: true }]
    });
    expect(leftOutSources(coverage)[0]?.segments).toBeNull();
  });

  it("turns a recorded reason into its message key", () => {
    expect(reasonSlug("notes cut short")).toBe("notes_cut_short");
  });
});
