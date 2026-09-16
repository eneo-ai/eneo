import type { Release } from "@eneo/whats-new";
import { describe, expect, it } from "vitest";
import { ANNOUNCEMENT_ENTRIES, announcementSummary } from "./announcement";

const entry = (id: string, extra = {}) => ({
  id,
  type: "new" as const,
  area: "chat" as const,
  title: { en: id, sv: id },
  body: { en: id, sv: id },
  ...extra
});

const release: Release = {
  version: "2.2.0",
  entries: ["a", "b", "c", "d", "e", "f", "g"].map((id) =>
    entry(id, id === "b" ? { audience: "admin" } : {})
  )
};

describe("announcement summary", () => {
  it("shows the first visible entries and counts the rest", () => {
    const user = announcementSummary(release, false);
    expect(user.entries.map((e) => e.id)).toEqual(["a", "c", "d", "e"]);
    expect(user).toMatchObject({ more: 2, total: 6 });

    const admin = announcementSummary(release, true);
    expect(admin.entries).toHaveLength(ANNOUNCEMENT_ENTRIES);
    expect(admin.entries.map((e) => e.id)).toContain("b");
    expect(admin).toMatchObject({ more: 3, total: 7 });
  });

  it("never reports a negative remainder", () => {
    expect(announcementSummary({ version: "1.0.0", entries: [entry("x")] }, false)).toMatchObject({
      more: 0,
      total: 1
    });
  });
});
