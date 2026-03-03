import { describe, expect, it } from "vitest";
import { getRedispatchToastKind } from "./flowRunRedispatchFeedback";

describe("getRedispatchToastKind", () => {
  it("returns success when at least one run was redispatched", () => {
    expect(getRedispatchToastKind(1)).toBe("success");
  });

  it("returns info when redispatch count is zero", () => {
    expect(getRedispatchToastKind(0)).toBe("info");
  });

  it("returns info for nullish values", () => {
    expect(getRedispatchToastKind(undefined)).toBe("info");
    expect(getRedispatchToastKind(null)).toBe("info");
  });
});
