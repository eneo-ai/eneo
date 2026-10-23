import { describe, expect, it } from "vitest";
import {
  capabilityBlockReason,
  modelSupportsToolCalling,
  readinessKey,
  toggleCapability
} from "./capabilities";

describe("capability selection", () => {
  it("keeps other functions when one is toggled", () => {
    expect(toggleCapability(["web_search"], "image_generation")).toEqual([
      "web_search",
      "image_generation"
    ]);
    expect(toggleCapability(["web_search", "image_generation"], "web_search")).toEqual([
      "image_generation"
    ]);
  });

  it("allows disabling an unavailable function, but guards new enablement", () => {
    expect(
      capabilityBlockReason({
        enabled: true,
        spaceEnabled: false,
        available: false,
        modelSupportsTools: false
      })
    ).toBeNull();
    expect(
      capabilityBlockReason({
        enabled: false,
        spaceEnabled: false,
        available: true,
        modelSupportsTools: true
      })
    ).toBe("space_disabled");
    expect(
      capabilityBlockReason({
        enabled: false,
        spaceEnabled: true,
        available: true,
        modelSupportsTools: false
      })
    ).toBe("model_no_tool_calling");
    expect(
      capabilityBlockReason({
        enabled: false,
        spaceEnabled: true,
        available: false,
        modelSupportsTools: true
      })
    ).toBe("no_active_provider");
  });

  it("treats only an explicit tool-calling flag as support, like the backend", () => {
    expect(modelSupportsToolCalling({ supports_tool_calling: true })).toBe(true);
    expect(modelSupportsToolCalling({ supports_tool_calling: false })).toBe(false);
    expect(modelSupportsToolCalling({ supports_tool_calling: null })).toBe(false);
    expect(modelSupportsToolCalling({})).toBe(false);
    expect(modelSupportsToolCalling(null)).toBe(false);
    expect(readinessKey("model_no_tool_calling")).toBe("tools_readiness_model_no_tool_calling");
  });
});
