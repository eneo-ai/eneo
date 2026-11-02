import { describe, expect, it } from "vitest";
import {
  assistantInsightViewSearch,
  readAssistantInsightView,
  validateAssistantInsightSearch
} from "./assistant-insights-view";
import type { InsightRange } from "@/features/insights/insights-range";
const fallback = { start: "2026-10-01", end: "2026-10-31" } as InsightRange;

describe("assistant insight URL filters", () => {
  it("reads Svelte's calendar range, followups and selected tab", () => {
    expect(
      readAssistantInsightView(
        new URLSearchParams("from=2026-09-01&to=2026-09-30&followups=false&tab=questions"),
        fallback
      )
    ).toEqual({
      range: { start: "2026-09-01", end: "2026-09-30" },
      includeFollowups: false,
      tab: "questions"
    });
  });
  it.each([
    "from=2026-02-30&to=2026-03-01",
    "from=2026-10-31&to=2026-10-01",
    "from=2026-01-01",
    "from=<script>&to=2026-01-01"
  ])("falls back for invalid or incomplete dates: %s", (query) => {
    expect(
      readAssistantInsightView(
        new URLSearchParams(query + "&tab=analysis&followups=oops"),
        fallback
      )
    ).toEqual({ range: fallback, includeFollowups: true, tab: "chat" });
  });
  it("writes the same view on reload while preserving unrelated parameters", () => {
    const view = readAssistantInsightView(
      new URLSearchParams("from=2026-09-01&to=2026-09-30&followups=false&tab=questions"),
      fallback
    );
    const query = assistantInsightViewSearch(view, "?other=keep");
    expect(new URLSearchParams(query).get("other")).toBe("keep");
    expect(readAssistantInsightView(new URLSearchParams(query), fallback)).toEqual(view);
    expect(
      validateAssistantInsightSearch(
        { from: ["2026-09-01", "bad"], to: "2026-09-30", followups: "false", tab: "questions" },
        fallback
      )
    ).toEqual({ from: "2026-09-01", to: "2026-09-30", followups: "false", tab: "questions" });
  });
});
