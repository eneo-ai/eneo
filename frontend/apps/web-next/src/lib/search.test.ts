import { describe, expect, it } from "vitest";
import { matchesSearch, searchTerms } from "./search";

describe("matchesSearch", () => {
  it("finds every word in any order, trimmed and case-insensitively", () => {
    expect(matchesSearch(["Policy for 2024"], " 2024 policy ")).toBe(true);
    expect(matchesSearch(["abc"], "abc ")).toBe(true);
    expect(matchesSearch(["Policy for 2024"], "policy 2025")).toBe(false);
  });

  it("matches a blank query", () => {
    expect(matchesSearch(["Policies"], "  ")).toBe(true);
    expect(matchesSearch([], "")).toBe(true);
  });

  it("searches numbers and skips empty values", () => {
    expect(matchesSearch(["Policies", 12, null, undefined, " "], "12 pol")).toBe(true);
    expect(matchesSearch(["Policies", null], "missing")).toBe(false);
  });

  it("does not match across the gap between two values", () => {
    expect(matchesSearch(["Budget", "assistant"], "getass")).toBe(false);
  });
});

describe("searchTerms", () => {
  it("splits the query into lower-cased words", () => {
    expect(searchTerms("  Policy\t2024 ")).toEqual(["policy", "2024"]);
    expect(searchTerms(" ")).toEqual([]);
  });
});
