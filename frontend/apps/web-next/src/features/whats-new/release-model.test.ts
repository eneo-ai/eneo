import { describe, expect, it } from "vitest";
import type { Release } from "@eneo/whats-new";
import {
  areasPresent,
  filterEntries,
  isReadRelease,
  pendingAnnouncement,
  shouldShowAnnouncement,
  tourEntries
} from "./release-model";

const release: Release = {
  version: "2.2.0",
  date: "2026-09-01",
  entries: [
    {
      id: "chat",
      type: "new",
      area: "chat",
      title: { en: "Chat", sv: "Chatt" },
      body: { en: "Body", sv: "Text" }
    },
    {
      id: "admin",
      type: "new",
      area: "admin",
      audience: "admin",
      title: { en: "Admin", sv: "Admin" },
      body: { en: "Body", sv: "Text" },
      showMe: { href: "/admin", anchor: "admin" }
    }
  ]
};

describe("What's new release behavior", () => {
  it("keeps announcement and read markers separate", () => {
    expect(pendingAnnouncement(true, release, null)).toBe(release);
    expect(pendingAnnouncement(true, release, "2.2.0")).toBeNull();
    expect(pendingAnnouncement(true, release, "2.3.0")).toBeNull();
    expect(pendingAnnouncement(true, release, undefined)).toBeNull();
    expect(pendingAnnouncement(false, release, null)).toBeNull();
    expect(isReadRelease(release, "2.1.0")).toBe(false);
    expect(isReadRelease(release, "2.2.0")).toBe(true);
  });

  it("does not announce a dated release to a newer account", () => {
    expect(shouldShowAnnouncement(release, "2026-09-02T00:00:00Z")).toBe(false);
    expect(shouldShowAnnouncement(release, "2026-08-31T00:00:00Z")).toBe(true);
    expect(shouldShowAnnouncement({ ...release, date: undefined }, "2026-10-01T00:00:00Z")).toBe(
      true
    );
  });

  it("hides admin content from non-admins in lists, filters, and tours", () => {
    expect(areasPresent(release, false)).toEqual(["chat"]);
    expect(
      filterEntries(release, { area: null, showMeOnly: false }, false).map((e) => e.id)
    ).toEqual(["chat"]);
    expect(tourEntries(release, false)).toEqual([]);
    expect(tourEntries(release, true).map((e) => e.id)).toEqual(["admin"]);
  });
});
