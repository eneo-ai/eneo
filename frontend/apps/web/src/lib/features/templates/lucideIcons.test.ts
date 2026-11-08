import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IconNode } from "@lucide/svelte";
import { createLucideRegistry } from "./lucideIcons";

const node: IconNode = [["path", { d: "M4 4h16v16H4z" }]];

describe("loadLucideIcons", () => {
  beforeEach(() => {
    vi.resetModules();
  });
  afterEach(() => {
    vi.doUnmock("virtual:lucide-icon-data");
  });

  it("does not keep a failed download, so the next call retries", async () => {
    vi.doMock("virtual:lucide-icon-data", () => {
      throw new Error("offline");
    });
    const { loadLucideIcons, loadLucideIcon, loadLucideIconOrNull } = await import("./lucideIcons");

    // Vitest wraps a throwing mock factory in its own error; any rejection is what matters here.
    await expect(loadLucideIcons()).rejects.toThrow();
    await expect(loadLucideIconOrNull("rocket")).resolves.toBeNull();

    vi.resetModules();
    vi.doMock("virtual:lucide-icon-data", () => ({
      default: { icons: { Rocket: ["rocket", node] }, aliases: {} }
    }));

    await expect(loadLucideIcon("rocket")).resolves.toEqual({ name: "rocket", iconNode: node });
  });

  it("resolves stored names, renamed ones included, against the installed Lucide set", async () => {
    const { loadLucideIcons } = await import("./lucideIcons");
    const icons = await loadLucideIcons();

    const house = icons.get("house");
    expect(house?.name).toBe("house");
    expect(house?.iconNode.length).toBeGreaterThan(0);
    expect(icons.get("home")).toBe(house);
    expect(icons.get("lucide-home")).toBe(house);
    expect(icons.get("house-icon")).toBe(house);
    expect(icons.names).toContain("House");
    expect(icons.names).not.toContain("Home");
  });
});

describe("createLucideRegistry", () => {
  const registry = createLucideRegistry({
    icons: { Rocket: ["rocket", node], House: ["house", node] },
    aliases: { Home: "House" }
  });
  const house = registry.get("house");

  it("offers only current icon names", () => {
    expect(registry.names).toEqual(["House", "Rocket"]);
  });

  it("resolves stored names, including aliases for renamed icons", () => {
    expect(registry.get("rocket")).toEqual({ name: "rocket", iconNode: node });
    expect(house).toEqual({ name: "house", iconNode: node });
    expect(registry.get("home")).toBe(house);
    expect(registry.get("house-icon")).toBe(house);
    expect(registry.get("lucide-house")).toBe(house);
    expect(registry.get("home-icon")).toBe(house);
  });

  it("returns null for unset, unknown and non-icon names", () => {
    expect(registry.get(null)).toBeNull();
    expect(registry.get("")).toBeNull();
    expect(registry.get("no-such-icon")).toBeNull();
    expect(registry.get("icon")).toBeNull();
    expect(registry.get("lucide")).toBeNull();
    expect(registry.get("lucide-house-icon")).toBeNull();
  });
});
