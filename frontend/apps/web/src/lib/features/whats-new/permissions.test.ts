import type { Permission } from "@eneo/eneo-js";
import { releases, visibleEntries, type Release, type ReleaseEntry } from "@eneo/whats-new";
import { describe, expect, it, vi } from "vitest";
import { hasPermission } from "$lib/core/hasPermission";
import { announcementSummary } from "./announcement";
import { areasPresent, countEntries, filterEntries } from "./filters";
import { tourSteps } from "./tour";

vi.mock("$app/navigation", () => ({ goto: vi.fn(), preloadData: vi.fn() }));
vi.mock("$lib/paraglide/runtime", () => ({ localizeHref: (href: string) => href }));

function entry(id: string, extra: Partial<ReleaseEntry> = {}): ReleaseEntry {
  return {
    id,
    type: "new",
    area: "account",
    title: { en: id, sv: id },
    body: { en: id, sv: id },
    showMe: { href: `/${id}`, anchor: id },
    ...extra
  };
}

const release: Release = {
  version: "2.3.0",
  entries: [
    entry("general"),
    entry("assistant", { area: "assistants", permissions: { allOf: ["assistants"] } }),
    entry("chat", { area: "chat", permissions: { anyOf: ["personal_chat", "assistants"] } }),
    entry("documents", {
      area: "chat",
      permissions: { allOf: ["file_creation"], anyOf: ["personal_chat", "assistants"] }
    }),
    entry("admin", { area: "admin", audience: "admin" }),
    entry("modules", { area: "admin", audience: "admin", permissions: { allOf: ["modules"] } })
  ]
};

function checker(permissions: Permission[]) {
  // A role named Admin grants only its explicitly listed permissions.
  return hasPermission({ roles: [{ id: "custom", name: "Admin", permissions }] });
}

describe("news uses actual feature permissions on every surface", () => {
  it.each<{ permissions: Permission[]; ids: string[] }>([
    { permissions: [], ids: ["general"] },
    { permissions: ["personal_chat"], ids: ["general", "chat"] },
    { permissions: ["assistants"], ids: ["general", "assistant", "chat"] },
    { permissions: ["file_creation"], ids: ["general"] },
    { permissions: ["personal_chat", "file_creation"], ids: ["general", "chat", "documents"] },
    { permissions: ["admin"], ids: ["general", "admin"] },
    { permissions: ["modules"], ids: ["general"] },
    { permissions: ["admin", "modules"], ids: ["general", "admin", "modules"] },
    {
      permissions: ["admin", "assistants", "file_creation", "modules"],
      ids: ["general", "assistant", "chat", "documents", "admin", "modules"]
    }
  ])(
    "keeps lists, counts, summaries and links consistent for $permissions",
    ({ permissions, ids }) => {
      const can = checker(permissions);
      const visible = visibleEntries(release, can);
      expect(visible.map((item) => item.id)).toEqual(ids);
      expect(filterEntries(release, { area: null, showMeOnly: true }, can)).toEqual(visible);
      expect(countEntries([release], can)).toBe(ids.length);
      expect(areasPresent([release], can)).toEqual([...new Set(visible.map((item) => item.area))]);
      expect(announcementSummary(release, can)).toEqual({
        entries: visible.slice(0, 4),
        total: ids.length,
        more: Math.max(0, ids.length - 4)
      });
      expect(tourSteps(release, can, "sv").map((step) => step.href)).toEqual(
        ids.map((id) => `/${id}`)
      );
      expect(filterEntries(release, { area: "assistants", showMeOnly: false }, can)).toEqual(
        visible.filter((item) => item.area === "assistants")
      );
    }
  );

  it("combines permissions across custom and predefined roles", () => {
    const can = hasPermission({
      roles: [{ id: "one", name: "One", permissions: ["personal_chat"] }],
      predefined_roles: [{ id: "two", name: "Two", permissions: ["file_creation"] }]
    });
    expect(visibleEntries(release, can).map((item) => item.id)).toEqual([
      "general",
      "chat",
      "documents"
    ]);
  });

  it("returns empty filters, counts, summaries and tours when every entry is hidden", () => {
    const restricted = { ...release, entries: release.entries.slice(1) };
    const can = checker([]);
    expect(filterEntries(restricted, { area: null, showMeOnly: false }, can)).toEqual([]);
    expect(areasPresent([restricted], can)).toEqual([]);
    expect(countEntries([restricted], can)).toBe(0);
    expect(announcementSummary(restricted, can)).toEqual({ entries: [], total: 0, more: 0 });
    expect(tourSteps(restricted, can, "en")).toEqual([]);
  });

  it("classifies published assistant, capability, skill and module news by their feature gates", () => {
    const ids = (permissions: Permission[]) =>
      releases.flatMap((r) => visibleEntries(r, checker(permissions)).map((e) => e.id));
    for (const permissions of [[], ["admin"], ["personal_chat"]] satisfies Permission[][]) {
      expect(ids(permissions)).not.toContain("prompt-guide");
      expect(ids(permissions)).not.toContain("assistant-attachment-modes");
      expect(ids(permissions)).not.toContain("modules-admin");
    }
    expect(ids(["assistants"])).toContain("prompt-guide");
    expect(ids(["admin", "modules"])).toContain("modules-admin");
    expect(ids(["skills"])).not.toContain("skills");
    expect(ids(["skills", "skills_management"])).toContain("skills");
    expect(ids(["personal_chat"])).not.toContain("file-creation-progress");
    expect(ids(["personal_chat", "file_creation"])).toContain("file-creation-progress");
    expect(ids([])).toEqual(
      expect.arrayContaining(["header-redesign", "self-service-password", "clearer-errors"])
    );
  });
});
