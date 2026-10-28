import { describe, expect, it } from "vitest";
import {
  defaultUsageRange,
  readUsageView,
  usageIntensity,
  usageListHref,
  usageRangeDayCount,
  usageRangeFromSearchParams,
  usageRangeQuery,
  usageThresholds,
  usageViewSearch,
  userUsageCost
} from "./usage";

describe("usage ranges", () => {
  it.each(["2026-99-99", "2026-02-30", "2025-02-29", "2026-07-01"])(
    "falls back for impossible or reversed ranges: %s",
    (from) => {
      const fallback = { from: "2026-06-01", to: "2026-06-30" };
      expect(usageRangeFromSearchParams({ from, to: "2026-06-30" }, fallback)).toEqual(fallback);
    }
  );
  it("creates a date-input range for the last 30 days", () => {
    expect(defaultUsageRange(new Date("2026-07-06T12:00:00Z"))).toEqual({
      from: "2026-06-06",
      to: "2026-07-06"
    });
  });

  it("parses supported search params and falls back on malformed values", () => {
    const fallback = { from: "2026-06-01", to: "2026-06-30" };

    expect(usageRangeFromSearchParams({ from: "2026-05-01", to: "2026-05-31" }, fallback)).toEqual({
      from: "2026-05-01",
      to: "2026-05-31"
    });
    expect(usageRangeFromSearchParams({ from: "bad", to: "2026-05-31" }, fallback)).toEqual(
      fallback
    );
  });

  it("converts date inputs to inclusive backend datetime parameters", () => {
    expect(usageRangeQuery({ from: "2026-06-01", to: "2026-06-30" })).toEqual({
      start_date: new Date("2026-06-01T00:00:00").toISOString(),
      end_date: new Date("2026-06-30T23:59:59").toISOString()
    });
  });

  it("counts the days between the range ends, as apps/web does", () => {
    expect(usageRangeDayCount({ from: "2026-06-01", to: "2026-07-01" })).toBe(30);
    expect(usageRangeDayCount({ from: "2026-06-01", to: "2026-06-01" })).toBe(1);
  });
});

describe("usage cost and intensity", () => {
  it("sums known model rates and ignores models without rates", () => {
    const cost = userUsageCost(
      {
        models_used: [
          {
            model_id: "model-a",
            model_name: "a",
            model_nickname: "A",
            model_org: "Org",
            model_provider: "Provider",
            input_token_usage: 100,
            output_token_usage: 50,
            total_token_usage: 150,
            request_count: 2
          },
          {
            model_id: "model-b",
            model_name: "b",
            model_nickname: "B",
            model_org: "Org",
            model_provider: "Provider",
            input_token_usage: 1000,
            output_token_usage: 1000,
            total_token_usage: 2000,
            request_count: 4
          }
        ]
      },
      new Map([["model-a", { input: 0.01, output: 0.02 }]])
    );

    expect(cost).toBe(2);
  });

  it("scales usage intensity thresholds with the selected range", () => {
    const range = { from: "2026-06-01", to: "2026-07-01" };
    expect(usageThresholds(range)).toEqual({ high: 500_000, medium: 50_000 });
    expect(usageThresholds({ from: "2026-06-01", to: "2026-06-16" })).toEqual({
      high: 250_000,
      medium: 25_000
    });
    expect(usageIntensity(600_000, range)).toBe("high");
    expect(usageIntensity(500_000, range)).toBe("medium");
    expect(usageIntensity(75_000, range)).toBe("medium");
    expect(usageIntensity(50_000, range)).toBe("low");
  });
});

describe("usage view in the URL", () => {
  const fallback = { from: "2026-06-01", to: "2026-07-01" };
  const read = (query: string) => readUsageView(new URLSearchParams(query), fallback);

  it("reads the tab, range, page, sort and search", () => {
    expect(
      read(
        "tab=users&from=2026-05-01&to=2026-05-31&page=7&sortBy=requests&sortOrder=asc&userSearch=%20anna%20"
      )
    ).toEqual({
      tab: "users",
      range: { from: "2026-05-01", to: "2026-05-31" },
      page: 7,
      sortBy: "requests",
      sortOrder: "asc",
      search: "anna"
    });
  });

  it("falls back to safe defaults for malformed deep links", () => {
    expect(
      read("tab=admin&from=2026-02-30&to=x&page=-1&sortBy=invalid&sortOrder=bad&userSearch=")
    ).toEqual({
      tab: "tokens",
      range: fallback,
      page: 1,
      sortBy: "total_tokens",
      sortOrder: "desc",
      search: ""
    });
    expect(read("page=1.5").page).toBe(1);
    expect(read(`userSearch=${"a".repeat(250)}`).search).toHaveLength(200);
  });

  it("writes only what differs from the defaults and keeps other parameters", () => {
    expect(usageViewSearch(read(""), "", fallback)).toBe("");
    expect(usageViewSearch(read(""), "?keep=1&page=4", fallback)).toBe("?keep=1");
    const view = read("tab=users&page=3&sortBy=username&sortOrder=asc&userSearch=anna lind");
    const search = usageViewSearch(
      { ...view, range: { from: "2026-05-01", to: "2026-05-31" } },
      "",
      fallback
    );
    expect(search).toBe(
      "?tab=users&from=2026-05-01&to=2026-05-31&page=3&sortBy=username&sortOrder=asc&userSearch=anna+lind"
    );
    expect(read(search.slice(1))).toMatchObject({ page: 3, search: "anna lind" });
  });

  it("leads back to the list a user's page was opened from", () => {
    const fromList = new URLSearchParams("tab=users&page=2&userSearch=anna&evil=https://x.test");
    expect(usageListHref(fromList)).toMatch(/^\/admin\/usage\?tab=users&page=2&userSearch=anna$/);
    expect(usageListHref(new URLSearchParams())).toBe("/admin/usage");
  });
});
