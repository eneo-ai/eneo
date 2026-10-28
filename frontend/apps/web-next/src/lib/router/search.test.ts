import { describe, expect, it } from "vitest";
import { parseSearch, stringifySearch } from "./search";

describe("search serialization", () => {
  it.each([
    "?tab=a&tab=b",
    "?next=%2Fspaces%2Fx%3Fy%3D1",
    "?page=2",
    "?q=",
    "?q=a+b",
    "?q=%C3%A5",
    "?z=1&a=2&m=3"
  ])("gives %s back unchanged", (search) => {
    expect(stringifySearch(parseSearch(search))).toBe(search);
  });

  it("keeps every value a string and a repeated key a list", () => {
    expect(parseSearch("?page=2&tab=a&tab=b&flag=true&next=%2Fspaces%2Fx%3Fy%3D1")).toEqual({
      page: "2",
      tab: ["a", "b"],
      flag: "true",
      next: "/spaces/x?y=1"
    });
  });

  it("keeps the order of the keys", () => {
    expect(Object.keys(parseSearch("?z=1&a=2&m=3"))).toEqual(["z", "a", "m"]);
  });

  it("writes numbers and booleans as text and leaves out missing values", () => {
    expect(stringifySearch({})).toBe("");
    expect(stringifySearch({ a: undefined, b: null })).toBe("");
    expect(stringifySearch({ page: 2, open: false, tab: ["a", undefined, "b"], q: "a b" })).toBe(
      "?page=2&open=false&tab=a&tab=b&q=a+b"
    );
  });
});
