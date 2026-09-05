import { describe, expect, it, vi } from "vitest";

// Messages resolve to their key so descriptor completeness can be checked
// without the compiled catalogs; icons are opaque markers in Node.
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));
vi.mock("lucide-svelte", () => ({ Globe: "Globe", Image: "Image" }));

import {
  CAPABILITIES,
  canUseCapability,
  getCapability,
  hasBuiltinProvider,
  isCapabilityPurpose,
  qualifyingProviders
} from "./capabilities";

describe("capability descriptors", () => {
  it("lists web search before image generation", () => {
    expect(CAPABILITIES.map((capability) => capability.purpose)).toEqual([
      "web_search",
      "image_generation"
    ]);
  });

  it("offers a built-in provider for image generation only", () => {
    expect(hasBuiltinProvider("image_generation")).toBe(true);
    expect(hasBuiltinProvider("web_search")).toBe(false);
    expect(hasBuiltinProvider("general")).toBe(false);
    expect(hasBuiltinProvider(null)).toBe(false);
    expect(hasBuiltinProvider(undefined)).toBe(false);
  });

  it("gives every capability an icon and non-empty messages", () => {
    for (const capability of CAPABILITIES) {
      expect(capability.icon).toBeTruthy();
      const { purpose, icon, builtinProvider, ...messages } = capability;
      void purpose;
      void icon;
      void builtinProvider;
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

describe("canUseCapability", () => {
  const userWith = (...granted: string[]) => ({
    hasPermission: (permission: string) => granted.includes(permission)
  });

  it("never gates general servers", () => {
    expect(canUseCapability(userWith(), "general")).toBe(true);
    expect(canUseCapability(userWith(), null)).toBe(true);
    expect(canUseCapability(userWith(), undefined)).toBe(true);
  });

  it("follows the role permission whose value equals the purpose", () => {
    expect(canUseCapability(userWith("web_search"), "web_search")).toBe(true);
    expect(canUseCapability(userWith("web_search"), "image_generation")).toBe(false);
    expect(canUseCapability(userWith(), "web_search")).toBe(false);
  });
});

describe("qualifyingProviders", () => {
  const provider = (purpose: string, level: number | null) => ({
    purpose,
    security_classification: level === null ? null : { security_level: level }
  });
  const servers = [
    provider("web_search", null),
    provider("web_search", 1),
    provider("web_search", 3),
    provider("image_generation", 3),
    provider("general", 3)
  ];

  it("offers every provider of the purpose to an unclassified space", () => {
    expect(qualifyingProviders(servers, "web_search", null)).toEqual(servers.slice(0, 3));
    expect(qualifyingProviders(servers, "web_search", undefined)).toEqual(servers.slice(0, 3));
  });

  it("requires a provider at or above a classified space's level", () => {
    expect(qualifyingProviders(servers, "web_search", { security_level: 2 })).toEqual([servers[2]]);
    expect(qualifyingProviders(servers, "web_search", { security_level: 3 })).toEqual([servers[2]]);
    expect(qualifyingProviders(servers, "web_search", { security_level: 4 })).toEqual([]);
  });

  it("never lets an unclassified provider qualify for a classified space", () => {
    expect(qualifyingProviders(servers, "web_search", { security_level: 0 })).toEqual([
      servers[1],
      servers[2]
    ]);
  });
});
