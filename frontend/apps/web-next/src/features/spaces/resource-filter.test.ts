import { describe, expect, it } from "vitest";
import { filterSpaceResources, matchesSearch } from "./resource-filter";

const items = [
  { name: "Budget assistant", description: "Drafts budget answers", type: "assistant" },
  { name: "Invoice app", description: "Extract fields from PDFs", type: null },
  { name: "Policy service", description: null, type: "service" }
];

describe("filterSpaceResources", () => {
  it("returns all items for a blank query", () => {
    expect(filterSpaceResources(items, " ")).toBe(items);
  });

  it("matches name, description, and type case-insensitively", () => {
    expect(filterSpaceResources(items, "pdfs").map((item) => item.name)).toEqual(["Invoice app"]);
    expect(filterSpaceResources(items, "SERVICE").map((item) => item.name)).toEqual([
      "Policy service"
    ]);
  });

  it("requires every search term to match the same item", () => {
    expect(filterSpaceResources(items, "budget drafts").map((item) => item.name)).toEqual([
      "Budget assistant"
    ]);
    expect(filterSpaceResources(items, "budget pdfs")).toEqual([]);
  });
});

describe("matchesSearch", () => {
  it("searches numbers and skips empty values", () => {
    expect(matchesSearch(["Policies", 12, null, undefined, " "], "12 pol")).toBe(true);
    expect(matchesSearch(["Policies", null], "missing")).toBe(false);
    expect(matchesSearch([], "")).toBe(true);
  });

  it("does not match across the gap between two values", () => {
    expect(matchesSearch(["Budget", "assistant"], "getass")).toBe(false);
  });
});
