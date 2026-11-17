import { describe, expect, it } from "vitest";
import {
  insightViewSearch,
  readInsightRangeSearch,
  readInsightViewSearch,
  validateInsightViewSearch
} from "./assistant-insights-view";
import type { InsightRange } from "@/features/insights/insights-range";
const fallback = { start: "2026-10-01", end: "2026-10-31" } as InsightRange;

describe("assistant insight URL period", () => {
  it("reads Svelte's calendar range", () => {
    expect(
      readInsightRangeSearch(new URLSearchParams("from=2026-09-01&to=2026-09-30"), fallback)
    ).toEqual({ start: "2026-09-01", end: "2026-09-30" });
  });
  it.each([
    "from=2026-02-30&to=2026-03-01",
    "from=2026-10-31&to=2026-10-01",
    "from=2026-01-01",
    "from=<script>&to=2026-01-01"
  ])("falls back for invalid or incomplete dates: %s", (query) => {
    expect(readInsightRangeSearch(new URLSearchParams(query), fallback)).toEqual(fallback);
  });
  it("writes the same filters on reload while preserving unrelated parameters", () => {
    const filters = readInsightViewSearch(
      new URLSearchParams("from=2026-09-01&to=2026-09-30&source=widget&compare=1"),
      fallback
    );
    expect(filters).toEqual({
      range: { start: "2026-09-01", end: "2026-09-30" },
      source: "widget",
      compare: true
    });
    const query = insightViewSearch(filters, "?other=keep");
    expect(new URLSearchParams(query).get("other")).toBe("keep");
    expect(readInsightViewSearch(new URLSearchParams(query), fallback)).toEqual(filters);
    // Every source and no comparison are the defaults: left out of the address.
    const plain = insightViewSearch({ ...filters, source: null, compare: false }, query);
    expect(new URLSearchParams(plain).has("source")).toBe(false);
    expect(new URLSearchParams(plain).has("compare")).toBe(false);
    // The older page's tab and follow-up switch, and unknown values, are left out of the address.
    expect(
      validateInsightViewSearch(
        {
          from: ["2026-09-01", "bad"],
          to: "2026-09-30",
          followups: "false",
          tab: "questions",
          source: "everyone",
          compare: "yes"
        },
        fallback
      )
    ).toEqual({ from: "2026-09-01", to: "2026-09-30" });
    expect(
      validateInsightViewSearch(
        { from: "2026-09-01", to: "2026-09-30", source: "api_key", compare: "1" },
        fallback
      )
    ).toEqual({ from: "2026-09-01", to: "2026-09-30", source: "api_key", compare: "1" });
  });
});
