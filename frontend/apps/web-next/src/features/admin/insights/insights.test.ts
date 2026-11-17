import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { nextTargetOffset } from "./insights";
import {
  insightPeriod,
  previousInsightRange,
  periodTotals,
  insightTrend,
  groupedInsightSeries
} from "./insights";
import { insightAggregatedQueryOptions } from "./insights";
import type { InsightRange } from "@/features/insights/insights-range";

describe("overview periods", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("includes whole local days without sharing midnight with the previous calendar period", () => {
    vi.stubEnv("TZ", "Europe/Stockholm");
    const range = { start: "2026-10-24", end: "2026-10-26" } as InsightRange;
    expect(insightPeriod(range)).toEqual({
      start: "2026-10-23T22:00:00.000Z",
      end: "2026-10-26T22:59:59.999999Z"
    });
    expect(previousInsightRange(range)).toEqual({ start: "2026-10-21", end: "2026-10-23" });
    expect(insightPeriod(previousInsightRange(range)).end).toBe("2026-10-23T21:59:59.999999Z");
  });

  it.each([
    ["2026-03-29", "2026-03-29", "2026-03-28T23:00:00.000Z", "2026-03-29T21:59:59.999999Z"],
    ["2026-10-25", "2026-10-25", "2026-10-24T22:00:00.000Z", "2026-10-25T22:59:59.999999Z"],
    ["2026-12-31", "2026-12-31", "2026-12-30T23:00:00.000Z", "2026-12-31T22:59:59.999999Z"]
  ])(
    "keeps complete local days at DST and year boundaries: %s",
    (start, end, expectedStart, expectedEnd) => {
      vi.stubEnv("TZ", "Europe/Stockholm");
      expect(insightPeriod({ start, end } as InsightRange)).toEqual({
        start: expectedStart,
        end: expectedEnd
      });
    }
  );

  it("sums hourly counts and expresses changes against the previous period, including zero baselines", () => {
    expect(
      periodTotals({
        assistants: [],
        sessions: [
          { created_at: "2026-10-01T00:00:00Z", count: 3 },
          { created_at: "2026-10-01T01:00:00Z", count: 5 }
        ],
        questions: []
      })
    ).toEqual({ assistants: 0, sessions: 8, questions: 0 });
    expect(insightTrend(15, 10)).toBe(50);
    expect(insightTrend(0, 10)).toBe(-100);
    expect(insightTrend(0, 0)).toBe(0);
    expect(insightTrend(5, 0)).toBeNull();
  });

  it("groups real hourly buckets by the viewer's date, weekday and hour", () => {
    vi.stubEnv("TZ", "Europe/Stockholm");
    const data = {
      assistants: [],
      sessions: [
        { created_at: "2026-10-25T23:00:00Z", count: 3 },
        { created_at: "2026-10-26T00:00:00Z", count: 2 }
      ],
      questions: []
    };
    expect(groupedInsightSeries(data, "date")).toEqual([
      { date: "2026-10-26", assistants: 0, sessions: 5, questions: 0 }
    ]);
    expect(groupedInsightSeries(data, "weekday")[0]).toMatchObject({ date: "0", sessions: 5 });
    expect(groupedInsightSeries(data, "hour").slice(0, 2)).toMatchObject([
      { date: "0", sessions: 3 },
      { date: "1", sessions: 2 }
    ]);
    expect(groupedInsightSeries(data, "hour")).toHaveLength(24);
  });
});

it("keys hourly aggregates by the viewer's zone and sends it without changing the instant bounds", async () => {
  const GET = vi.fn().mockResolvedValue({
    data: { assistants: [], sessions: [], questions: [] },
    response: new Response("{}")
  });
  const api = { GET } as unknown as EneoClient;
  const range = { start: "2026-04-10T18:30:00.000Z", end: "2026-04-11T18:29:59.999999Z" };
  const query = insightAggregatedQueryOptions(api, range, "Asia/Kolkata");
  expect(query.queryKey).toEqual(["admin-insights-aggregated", range, "Asia/Kolkata"]);
  const client = new QueryClient();
  try {
    await client.query(query);
    expect(GET).toHaveBeenCalledWith("/api/v1/analysis/metadata-statistics/aggregated/", {
      params: {
        query: { start_date: range.start, end_date: range.end, time_zone: "Asia/Kolkata" }
      },
      signal: expect.any(AbortSignal)
    });
    expect(insightAggregatedQueryOptions(api, range).queryKey).toContain(
      Intl.DateTimeFormat().resolvedOptions().timeZone
    );
  } finally {
    client.clear();
  }
});

describe("viewer-aligned hourly aggregates", () => {
  afterEach(() => vi.unstubAllEnvs());
  it.each([
    ["Asia/Kolkata", "2026-04-10T17:30:00Z", "2026-04-10T18:30:00Z"],
    ["Asia/Kathmandu", "2026-04-10T17:15:00Z", "2026-04-10T18:15:00Z"]
  ])("keeps local midnight and weighted hour counts in %s", (zone, before, after) => {
    vi.stubEnv("TZ", zone);
    const data = {
      assistants: [],
      sessions: [
        { created_at: before, count: 2 },
        { created_at: after, count: 3 }
      ],
      questions: []
    };
    expect(groupedInsightSeries(data, "date")).toMatchObject([
      { date: "2026-04-10", sessions: 2 },
      { date: "2026-04-11", sessions: 3 }
    ]);
    const hours = groupedInsightSeries(data, "hour");
    expect(hours[23]?.sessions).toBe(2);
    expect(hours[0]?.sessions).toBe(3);
  });
});

describe("the overview table's pages", () => {
  it("asks for the next offset until every target is loaded", () => {
    const items = (count: number) => Array.from({ length: count }, () => ({}));
    expect(nextTargetOffset({ offset: 0, items: items(25), total_count: 60 })).toBe(25);
    expect(nextTargetOffset({ offset: 50, items: items(10), total_count: 60 })).toBeUndefined();
    // A page that came back empty (fewer targets since) ends the list.
    expect(nextTargetOffset({ offset: 25, items: [], total_count: 60 })).toBeUndefined();
  });
});
