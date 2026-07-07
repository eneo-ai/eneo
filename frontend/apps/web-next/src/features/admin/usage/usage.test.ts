import { describe, expect, it } from "vitest";
import {
  defaultUsageRange,
  usageIntensity,
  usageRangeDayCount,
  usageRangeFromSearchParams,
  usageRangeQuery,
  userUsageCost
} from "./usage";

describe("usage ranges", () => {
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

  it("counts inclusive range days for usage thresholds", () => {
    expect(usageRangeDayCount({ from: "2026-06-01", to: "2026-06-30" })).toBe(30);
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
    const range = { from: "2026-06-01", to: "2026-06-30" };
    expect(usageIntensity(600_000, range)).toBe("high");
    expect(usageIntensity(75_000, range)).toBe("medium");
    expect(usageIntensity(10_000, range)).toBe("low");
  });
});
