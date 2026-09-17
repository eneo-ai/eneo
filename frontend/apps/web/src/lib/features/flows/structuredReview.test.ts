import { describe, expect, it } from "vitest";
import { reviewChangedPaths, reviewPropertyPath } from "./structuredReview";

describe("review changes", () => {
  it("ignores object key order and marks changed fields and their sections", () => {
    expect(reviewChangedPaths({ a: 1, b: 2 }, { b: 2, a: 1 }).size).toBe(0);
    expect(
      reviewChangedPaths(
        { section: { answer: "Before", kept: true } },
        {
          section: { answer: "After", kept: true }
        }
      )
    ).toEqual(new Set(["/section/answer", "/section", ""]));
  });

  it("compares arrays as a whole without inventing item identity after removal or replacement", () => {
    const before = { rows: [{ name: "One" }, { name: "Two" }] };
    expect(reviewChangedPaths(before, { rows: [{ name: "Two" }] })).toEqual(new Set(["/rows", ""]));
    expect(reviewChangedPaths(before, { rows: [{ name: "Two" }, { name: "New" }] })).toEqual(
      new Set(["/rows", ""])
    );
    expect(reviewChangedPaths(before, before).size).toBe(0);
  });

  it("includes removed and added properties and distinguishes punctuation in field names", () => {
    const before = { "a/b": false, a: { b: false }, removed: "" };
    const after = { "a/b": true, a: { b: false }, added: null };
    expect(reviewChangedPaths(before, after)).toEqual(new Set(["/a~1b", "/removed", "/added", ""]));
    expect(reviewPropertyPath("", "~a/b")).toBe("/~0a~1b");
  });
});
