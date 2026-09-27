import { describe, expect, it, vi } from "vitest";
import { createLucideRegistry } from "./lucideIcons";

describe("loadLucideIcons", () => {
  it("does not keep a failed download, so the next call retries", async () => {
    vi.doMock("@lucide/svelte", () => {
      throw new Error("offline");
    });
    const { loadLucideIcons, loadLucideIcon, loadLucideIconOrNull } = await import("./lucideIcons");

    // Vitest wraps a throwing mock factory in its own error; any rejection is what matters here.
    await expect(loadLucideIcons()).rejects.toThrow();
    await expect(loadLucideIconOrNull("rocket")).resolves.toBeNull();

    vi.resetModules();
    const Rocket = {};
    vi.doMock("@lucide/svelte", () => ({ icons: { Rocket } }));

    await expect(loadLucideIcon("rocket")).resolves.toBe(Rocket);
  });
});

describe("createLucideRegistry", () => {
  const House = {};
  const Rocket = {};
  const registry = createLucideRegistry({
    icons: { Rocket, House },
    Home: House,
    HouseIcon: House,
    Icon: {},
    setLucideProps: () => {}
  } as never);

  it("offers only current icon names", () => {
    expect(registry.names).toEqual(["House", "Rocket"]);
  });

  it("resolves stored names, including aliases for renamed icons", () => {
    expect(registry.get("rocket")).toBe(Rocket);
    expect(registry.get("home")).toBe(House);
    expect(registry.get("house-icon")).toBe(House);
  });

  it("returns null for unset, unknown and non-icon names", () => {
    expect(registry.get(null)).toBeNull();
    expect(registry.get("")).toBeNull();
    expect(registry.get("no-such-icon")).toBeNull();
    expect(registry.get("icon")).toBeNull();
  });
});
