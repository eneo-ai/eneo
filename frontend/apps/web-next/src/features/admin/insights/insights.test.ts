import { describe, expect, it } from "vitest";
import { mergeInsightSeries } from "./insights";

describe("mergeInsightSeries", () => {
  it("merges the three per-day series, fills gaps with 0, and sorts by day", () => {
    const rows = mergeInsightSeries({
      assistants: [{ created_at: "2026-06-02T00:00:00Z", count: 2 }],
      sessions: [
        { created_at: "2026-06-01T08:00:00Z", count: 5 },
        { created_at: "2026-06-02T09:00:00Z", count: 3 }
      ],
      questions: [{ created_at: "2026-06-01T10:00:00Z", count: 9 }]
    });

    expect(rows).toEqual([
      { date: "2026-06-01", assistants: 0, sessions: 5, questions: 9 },
      { date: "2026-06-02", assistants: 2, sessions: 3, questions: 0 }
    ]);
  });

  it("collapses multiple same-day buckets into one row", () => {
    const rows = mergeInsightSeries({
      assistants: [],
      sessions: [
        { created_at: "2026-06-01T01:00:00Z", count: 1 },
        { created_at: "2026-06-01T20:00:00Z", count: 4 }
      ],
      questions: []
    });
    expect(rows).toEqual([{ date: "2026-06-01", assistants: 0, sessions: 5, questions: 0 }]);
  });

  it("returns an empty array when all series are empty", () => {
    expect(mergeInsightSeries({ assistants: [], sessions: [], questions: [] })).toEqual([]);
  });
});
