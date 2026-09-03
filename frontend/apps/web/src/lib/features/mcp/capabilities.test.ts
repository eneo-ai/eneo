import { describe, expect, it, vi } from "vitest";

// Messages resolve to their key so descriptor completeness can be checked
// without the compiled catalogs; icons are opaque markers in Node.
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));
vi.mock("lucide-svelte", () => ({ Globe: "Globe", Image: "Image" }));

import { CAPABILITIES, getCapability, isCapabilityPurpose } from "./capabilities";

describe("capability descriptors", () => {
  it("lists web search before image generation", () => {
    expect(CAPABILITIES.map((capability) => capability.purpose)).toEqual([
      "web_search",
      "image_generation"
    ]);
  });

  it("gives every capability an icon and non-empty messages", () => {
    for (const capability of CAPABILITIES) {
      expect(capability.icon).toBeTruthy();
      const { purpose, icon, ...messages } = capability;
      void purpose;
      void icon;
      for (const [key, message] of Object.entries(messages)) {
        expect(typeof message, `${capability.purpose}.${key}`).toBe("function");
        expect(message().length, `${capability.purpose}.${key}`).toBeGreaterThan(0);
      }
    }
  });

  it("treats every non-general purpose as a capability", () => {
    expect(isCapabilityPurpose("general")).toBe(false);
    expect(isCapabilityPurpose(null)).toBe(false);
    expect(isCapabilityPurpose(undefined)).toBe(false);
    expect(isCapabilityPurpose("web_search")).toBe(true);
    expect(isCapabilityPurpose("image_generation")).toBe(true);
    expect(isCapabilityPurpose("future_capability")).toBe(true);
  });

  it("resolves descriptors by purpose", () => {
    expect(getCapability("image_generation")?.purpose).toBe("image_generation");
    expect(getCapability("general")).toBeUndefined();
  });
});
