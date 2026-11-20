import { describe, expect, it } from "vitest";
import { disabledCapabilitiesForRequest } from "./chat-capabilities";

describe("chat capability controls", () => {
  it("sends exactly the capabilities the user turned off, by purpose", () => {
    expect(disabledCapabilitiesForRequest(new Set(["image_generation"]))).toEqual([
      "image_generation"
    ]);
    expect(disabledCapabilitiesForRequest(new Set())).toBeUndefined();
  });
});
