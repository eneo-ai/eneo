import { describe, expect, it, vi } from "vitest";

describe("loadLucideIcons", () => {
  it("does not keep a failed download, so the next call retries", async () => {
    vi.doMock("lucide-svelte", () => {
      throw new Error("offline");
    });
    const { loadLucideIcons, loadLucideIcon, loadLucideIconOrNull } = await import("./lucideIcons");

    // Vitest wraps a throwing mock factory in its own error; any rejection is what matters here.
    await expect(loadLucideIcons()).rejects.toThrow();
    await expect(loadLucideIconOrNull("rocket")).resolves.toBeNull();

    vi.resetModules();
    const Rocket = {};
    vi.doMock("lucide-svelte", () => ({ Rocket }));

    await expect(loadLucideIcon("rocket")).resolves.toBe(Rocket);
  });
});
