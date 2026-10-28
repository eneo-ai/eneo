import { describe, expect, it } from "vitest";
import { filterSpaceResources } from "./resource-filter";

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
