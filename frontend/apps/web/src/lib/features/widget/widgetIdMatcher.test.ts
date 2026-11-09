import { describe, expect, it } from "vitest";
// SvelteKit reads every file in the matchers folder as a matcher, so the test lives here.
import { match } from "$lib/core/params/widgetId";

describe("widgetId route matcher", () => {
  it("accepts exactly the form the backend issues", () => {
    expect(match("wgt_0123456789abcdefABCDEF")).toBe(true);
  });

  it.each([
    "wgt_x/../../foo",
    "wgt_x%2F..%2F..%2Ffoo",
    "wgt_0123456789abcdefABCDE",
    "wgt_0123456789abcdefABCDEF0",
    "wgt_0123456789abcdefABCDE_",
    "wdg_0123456789abcdefABCDEF",
    ""
  ])("refuses %s", (value) => {
    expect(match(value)).toBe(false);
  });
});
