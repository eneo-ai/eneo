import { describe, expect, it } from "vitest";
import {
  estimateCostFromTokens,
  formatCostPerMillionTokens,
  formatCostUSD,
  formatTokens,
  getDeprecationStatus
} from "./format-model-stats";
import { sortModels } from "./sort-models";

describe("formatTokens", () => {
  it("renders K/M with adaptive precision and a dash for nullish/zero", () => {
    expect(formatTokens(null)).toBe("–");
    expect(formatTokens(0)).toBe("–");
    expect(formatTokens(512)).toBe("512");
    expect(formatTokens(128_000)).toBe("128K");
    expect(formatTokens(1_000_000)).toBe("1M");
    expect(formatTokens(1_500_000)).toBe("1.5M");
  });
});

describe("formatCostPerMillionTokens", () => {
  it("scales per-token cost to per-1M USD with adaptive precision", () => {
    expect(formatCostPerMillionTokens(null)).toBeNull();
    expect(formatCostPerMillionTokens(0)).toBe("$0");
    expect(formatCostPerMillionTokens(0.000003)).toBe("$3.00");
    expect(formatCostPerMillionTokens(0.0000006)).toBe("$0.6");
    expect(formatCostPerMillionTokens(0.00015)).toBe("$150");
    expect(formatCostPerMillionTokens("0.000003")).toBe("$3.00");
  });
});

describe("formatCostUSD", () => {
  it("formats absolute totals and guards nullish", () => {
    expect(formatCostUSD(null)).toBe("–");
    expect(formatCostUSD(0)).toBe("$0");
    expect(formatCostUSD(12.5)).toBe("$12.50");
    expect(formatCostUSD(250)).toBe("$250");
  });
});

describe("estimateCostFromTokens", () => {
  it("applies per-token rates and returns null when no rate is on record", () => {
    expect(estimateCostFromTokens(1000, 500, {})).toBeNull();
    expect(
      estimateCostFromTokens(1_000_000, 1_000_000, {
        input_cost_per_token: 0.000001,
        output_cost_per_token: 0.000002
      })
    ).toBeCloseTo(3, 5);
  });
});

describe("getDeprecationStatus", () => {
  it("classifies by date relative to a supplied today", () => {
    expect(getDeprecationStatus({ deprecation_date: null }, "2026-01-01")).toEqual({
      kind: "active",
      date: null
    });
    expect(getDeprecationStatus({ deprecation_date: "2025-12-31" }, "2026-01-01")).toEqual({
      kind: "deprecated",
      date: "2025-12-31"
    });
    expect(getDeprecationStatus({ deprecation_date: "2026-06-01" }, "2026-01-01")).toEqual({
      kind: "retiring",
      date: "2026-06-01"
    });
  });
});

describe("sortModels", () => {
  it("groups by org then nickname, without mutating the input", () => {
    const input = [
      { id: "1", org: "OpenAI", nickname: "GPT-4o" },
      { id: "2", org: "Anthropic", nickname: "Sonnet" },
      { id: "3", org: "Anthropic", nickname: "Haiku" }
    ];
    const out = sortModels(input);
    expect(out.map((m) => m.id)).toEqual(["3", "2", "1"]);
    expect(input.map((m) => m.id)).toEqual(["1", "2", "3"]);
  });
});
