import type { Release } from "@eneo/whats-new";
import { describe, expect, it } from "vitest";
import {
  applyFilters,
  areasPresent,
  countEntries,
  hasUnreadRelease,
  isReadRelease
} from "./filters";

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

const all = { area: null, showMeOnly: false, showRead: true };

describe("what's new filters", () => {
  it("marks releases up to the version seen at open as read", () => {
    expect(isReadRelease(releases[0], "2.2.0")).toBe(false);
    expect(isReadRelease(releases[1], "2.2.0")).toBe(true);
    expect(isReadRelease(releases[2], "2.2.0")).toBe(true);
    expect(isReadRelease(releases[2], null)).toBe(false);
    expect(hasUnreadRelease(releases, "2.3.0")).toBe(false);
    expect(hasUnreadRelease(releases, "2.2.0")).toBe(true);
  });

  it("hides read releases unless asked to show them", () => {
    const unreadOnly = applyFilters(releases, { ...all, showRead: false }, "2.2.0", true);
    expect(unreadOnly.map((r) => r.version)).toEqual(["2.3.0"]);
    expect(unreadOnly[0].read).toBe(false);

    const withRead = applyFilters(releases, all, "2.2.0", true);
    expect(withRead.map((r) => [r.version, r.read])).toEqual([
      ["2.3.0", false],
      ["2.2.0", true],
      ["2.1.0", true]
    ]);
  });

  it("filters by area and Show me, dropping releases that end up empty", () => {
    const chat = applyFilters(releases, { ...all, area: "chat" }, null, true);
    expect(chat.map((r) => [r.version, r.entries.map((e) => e.id)])).toEqual([
      ["2.3.0", ["a"]],
      ["2.1.0", ["d"]]
    ]);

    const showMe = applyFilters(releases, { ...all, showMeOnly: true }, null, true);
    expect(showMe.map((r) => r.entries.map((e) => e.id))).toEqual([["a"]]);
  });

  it("respects the audience in filters, areas and counts", () => {
    expect(applyFilters(releases, all, null, false)[0].entries.map((e) => e.id)).toEqual(["a"]);
    expect(areasPresent(releases, true)).toEqual(["chat", "admin", "knowledge"]);
    expect(areasPresent(releases, false)).toEqual(["chat", "knowledge"]);
    expect(countEntries(releases, true)).toBe(4);
    expect(countEntries(releases, false)).toBe(3);
  });
});
