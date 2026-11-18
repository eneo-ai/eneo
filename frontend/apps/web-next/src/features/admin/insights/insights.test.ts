import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { analysisAnswerText, assistantActivityRows } from "./insights";
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

describe("assistantActivityRows", () => {
  it("aggregates session and question metadata by assistant id and sorts by activity", () => {
    const rows = assistantActivityRows({
      assistants: [],
      sessions: [
        {
          id: "session-1",
          assistant_id: "assistant-a",
          group_chat_id: null,
          created_at: "2026-06-01T08:00:00Z"
        },
        {
          id: "session-2",
          assistant_id: "assistant-b",
          group_chat_id: null,
          created_at: "2026-06-01T09:00:00Z"
        },
        {
          id: "session-3",
          assistant_id: null,
          group_chat_id: "group-1",
          created_at: "2026-06-01T10:00:00Z"
        }
      ],
      questions: [
        {
          id: "question-1",
          assistant_id: "assistant-b",
          session_id: "session-2",
          created_at: "2026-06-01T09:10:00Z"
        },
        {
          id: "question-2",
          assistant_id: "assistant-a",
          session_id: "session-1",
          created_at: "2026-06-01T08:10:00Z"
        },
        {
          id: "question-3",
          assistant_id: "assistant-a",
          session_id: "session-1",
          created_at: "2026-06-01T08:20:00Z"
        },
        {
          id: "question-4",
          assistant_id: null,
          session_id: "session-3",
          created_at: "2026-06-01T10:10:00Z"
        }
      ]
    });

    expect(rows).toEqual([
      {
        assistantId: "assistant-a",
        sessions: 1,
        questions: 2,
        latestAt: "2026-06-01T08:20:00Z"
      },
      {
        assistantId: "assistant-b",
        sessions: 1,
        questions: 1,
        latestAt: "2026-06-01T09:10:00Z"
      }
    ]);
  });

  it("respects the requested row limit", () => {
    const rows = assistantActivityRows(
      {
        assistants: [],
        sessions: [
          {
            id: "session-1",
            assistant_id: "assistant-a",
            group_chat_id: null,
            created_at: "2026-06-01T08:00:00Z"
          },
          {
            id: "session-2",
            assistant_id: "assistant-b",
            group_chat_id: null,
            created_at: "2026-06-01T09:00:00Z"
          }
        ],
        questions: []
      },
      1
    );

    expect(rows).toHaveLength(1);
  });
});

describe("analysisAnswerText", () => {
  it("extracts the backend answer string from unknown JSON", () => {
    expect(analysisAnswerText({ answer: "Use fewer follow-up prompts." })).toBe(
      "Use fewer follow-up prompts."
    );
  });

  it("returns null for unsupported payload shapes", () => {
    expect(analysisAnswerText(null)).toBeNull();
    expect(analysisAnswerText({ answer: 12 })).toBeNull();
    expect(analysisAnswerText(["answer"])).toBeNull();
  });
});
