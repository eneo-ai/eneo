import { describe, expect, it } from "vitest";
import { flattenPages, nextPageCursor, type CursorPage } from "./pagination";

function page(items: string[], next_cursor: string | null = null): CursorPage<string> {
  return { items, total_count: 10, limit: items.length, next_cursor };
}

describe("nextPageCursor", () => {
  it("returns the cursor while more pages exist", () => {
    expect(nextPageCursor(page(["a"], "cursor-2"))).toBe("cursor-2");
  });

  it("returns undefined (stop fetching) on the last page", () => {
    expect(nextPageCursor(page(["a"], null))).toBeUndefined();
    expect(nextPageCursor({ items: [], total_count: 0 })).toBeUndefined();
  });
});

describe("flattenPages", () => {
  it("concatenates items across pages in order", () => {
    expect(flattenPages([page(["a", "b"], "c2"), page(["c"])])).toEqual(["a", "b", "c"]);
  });

  it("returns an empty list before the first page arrives", () => {
    expect(flattenPages(undefined)).toEqual([]);
  });
});
