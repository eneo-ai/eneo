import type { Release } from "@eneo/whats-new";
import { describe, expect, it } from "vitest";
import { areasPresent, countEntries, filterEntries, isReadRelease } from "./filters";

const entry = (id: string, area: Release["entries"][number]["area"], extra = {}) => ({
  id,
  type: "new" as const,
  area,
  title: { en: id, sv: id },
  body: { en: id, sv: id },
  ...extra
});

const releases: Release[] = [
  {
    version: "2.3.0",
    entries: [
      entry("a", "chat", { showMe: { href: "/account", anchor: "x" } }),
      entry("b", "admin", { audience: "admin" })
    ]
  },
  { version: "2.2.0", entries: [entry("c", "knowledge")] },
  { version: "2.1.0", entries: [entry("d", "chat")] }
];

const all = { area: null, showMeOnly: false };

describe("what's new filters", () => {
  it("marks releases up to the version seen at open as read", () => {
    expect(isReadRelease(releases[0], "2.2.0")).toBe(false);
    expect(isReadRelease(releases[1], "2.2.0")).toBe(true);
    expect(isReadRelease(releases[2], "2.2.0")).toBe(true);
    expect(isReadRelease(releases[2], null)).toBe(false);
  });

  it("narrows one release by area and Show me, respecting the audience", () => {
    expect(filterEntries(releases[0], all, true).map((e) => e.id)).toEqual(["a", "b"]);
    expect(filterEntries(releases[0], all, false).map((e) => e.id)).toEqual(["a"]);
    expect(filterEntries(releases[0], { ...all, area: "admin" }, true).map((e) => e.id)).toEqual([
      "b"
    ]);
    expect(filterEntries(releases[0], { ...all, showMeOnly: true }, true).map((e) => e.id)).toEqual(
      ["a"]
    );
    expect(filterEntries(releases[1], { ...all, showMeOnly: true }, true)).toEqual([]);
  });

  it("lists areas and counts for the audience", () => {
    expect(areasPresent(releases, true)).toEqual(["chat", "admin", "knowledge"]);
    expect(areasPresent([releases[1]], true)).toEqual(["knowledge"]);
    expect(countEntries(releases, true)).toBe(4);
    expect(countEntries(releases, false)).toBe(3);
  });
});
