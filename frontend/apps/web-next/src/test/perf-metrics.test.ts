import { describe, expect, it } from "vitest";
import { parseRuns, quantile, summarize, worstInteractionMs } from "../../tests/perf/metrics";

describe("perf baseline metrics", () => {
  it("counts only interactions that started at or after the measurement start", () => {
    const entries = [
      { interactionId: 7, startTime: 1_000, duration: 24 },
      // pointerover and other non-interaction events carry interactionId 0
      { interactionId: 0, startTime: 1_100, duration: 200 },
      // the chat submission before the measurement started
      { interactionId: 3, startTime: 400, duration: 120 },
      { interactionId: 8, startTime: 1_200, duration: 32 }
    ];
    expect(worstInteractionMs(entries, 1_000)).toBe(32);
    expect(worstInteractionMs([], 0)).toBe(0);
  });

  it("rejects RUNS that is not a positive integer", () => {
    expect(parseRuns(undefined)).toBe(10);
    expect(parseRuns("3")).toBe(3);
    for (const bad of ["0", "-1", "2.5", "abc", ""]) {
      expect(() => parseRuns(bad)).toThrow(/RUNS must be a positive integer/);
    }
  });

  it("summarizes medians and p75 per route and metric", () => {
    expect(quantile([4, 1, 3, 2], 0.5)).toBe(2.5);
    expect(summarize({ "/a": { lcp: [1, 2, 3, 4, 5] } })).toEqual({
      "/a": { lcp: { median: 3, p75: 4, mean: 3 } }
    });
  });
});
