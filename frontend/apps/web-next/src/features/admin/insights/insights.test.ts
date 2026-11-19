import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import type { InsightRange } from "@/features/insights/insights-range";
import {
  insightPeriod,
  insightTargetsActivityQueryOptions,
  insightTargetsSummaryQueryOptions,
  nextTargetOffset
} from "./insights";
import {
  insightsPageHref,
  insightsPageSearch,
  readInsightsPageSearch,
  validateInsightsPageSearch
} from "./insights-page-search";

describe("overview periods", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("includes whole local days, the last one up to its last microsecond", () => {
    vi.stubEnv("TZ", "Europe/Stockholm");
    const range = { start: "2026-10-24", end: "2026-10-26" } as InsightRange;
    expect(insightPeriod(range)).toEqual({
      start: "2026-10-23T22:00:00.000Z",
      end: "2026-10-26T22:59:59.999999Z"
    });
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
});

describe("the overview's address", () => {
  const fallback = { start: "2026-10-20", end: "2026-11-18" } as InsightRange;
  const range = { start: "2026-09-01", end: "2026-09-30" } as InsightRange;

  it("reads the page's state and writes it back, the defaults left out", () => {
    const defaults = readInsightsPageSearch(new URLSearchParams(), fallback);
    expect(defaults).toEqual({
      range: fallback,
      compare: false,
      unusedOnly: false,
      search: "",
      sort: { by: "conversations", order: "desc" }
    });
    expect(insightsPageSearch(defaults, fallback)).toBe("?");

    const query = insightsPageSearch(
      {
        range,
        compare: true,
        unusedOnly: true,
        search: "bygg",
        sort: { by: "name", order: "asc" }
      },
      fallback
    );
    expect(query).toBe(
      "?from=2026-09-01&to=2026-09-30&compare=1&activity=unused&q=bygg&sort=name&order=asc"
    );
    expect(readInsightsPageSearch(new URLSearchParams(query), fallback)).toEqual({
      range,
      compare: true,
      unusedOnly: true,
      search: "bygg",
      sort: { by: "name", order: "asc" }
    });
    // A column without an order starts as a click on it would.
    expect(readInsightsPageSearch(new URLSearchParams("sort=questions"), fallback).sort).toEqual({
      by: "questions",
      order: "desc"
    });
  });

  it("keeps only what the route understands, as it was given", () => {
    expect(
      validateInsightsPageSearch({
        from: "2026-09-01",
        to: "2026-09-30",
        compare: "1",
        activity: "unused",
        q: "  bygg  ",
        sort: "name",
        order: "asc",
        other: "x"
      })
    ).toEqual({
      from: "2026-09-01",
      to: "2026-09-30",
      compare: "1",
      activity: "unused",
      q: "bygg",
      sort: "name",
      order: "asc"
    });
    expect(
      validateInsightsPageSearch({
        from: "2026-09-30",
        to: "2026-09-01",
        compare: "yes",
        activity: "all",
        sort: "ratings",
        order: "up"
      })
    ).toEqual({});
  });

  it("leads back from an assistant's insights on the same period and comparison", () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date(2026, 10, 18, 12) });
    try {
      expect(insightsPageHref(range, true)).toBe(
        "/admin/insights?from=2026-09-01&to=2026-09-30&compare=1"
      );
      // The default period (the last 30 days) is no parameter.
      expect(
        insightsPageHref({ start: "2026-10-19", end: "2026-11-18" } as InsightRange, false)
      ).toBe("/admin/insights");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("the overview's reads", () => {
  const range = { start: "2026-09-01", end: "2026-09-30" } as InsightRange;

  async function read(query: Parameters<QueryClient["query"]>[0]) {
    const client = new QueryClient();
    try {
      return await client.query(query);
    } finally {
      client.clear();
    }
  }

  it("reads the tiles from the target list unfiltered, one row long", async () => {
    const GET = vi.fn().mockResolvedValue({ data: {}, response: new Response("{}") });
    const api = { GET } as unknown as EneoClient;
    const query = insightTargetsSummaryQueryOptions(api, range, true);
    expect(query.queryKey).toEqual(["admin-insights-targets", "summary", range, true]);
    await read(query as never);
    expect(GET.mock.calls[0]![1].params.query).toMatchObject({
      compare: true,
      sort: "conversations",
      order: "desc",
      activity: "all",
      limit: 1,
      offset: 0
    });
    expect(GET.mock.calls[0]![1].params.query.q).toBeUndefined();
  });

  it("reads the organisation's days in the browser's time zone", async () => {
    const GET = vi.fn().mockResolvedValue({ data: { days: [] }, response: new Response("{}") });
    const api = { GET } as unknown as EneoClient;
    await read(insightTargetsActivityQueryOptions(api, range) as never);
    expect(GET).toHaveBeenCalledWith("/api/v1/analysis/targets/activity/", {
      params: {
        query: {
          start_time: expect.any(String),
          end_time: expect.any(String),
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
        }
      },
      signal: expect.any(AbortSignal)
    });
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
