import type { Release } from "@eneo/whats-new";
import { describe, expect, it } from "vitest";
import { announcementSummary } from "./announcement";

const entry = (id: string, extra = {}) => ({
  id,
  type: "new" as const,
  area: "chat" as const,
  title: { en: `${id} en`, sv: `${id} sv` },
  body: { en: id, sv: id },
  ...extra
});

const release: Release = {
  version: "2.2.0",
  entries: [entry("a"), entry("b", { audience: "admin" }), entry("c"), entry("d"), entry("e")]
};

describe("announcement summary", () => {
  it("names the first visible titles in the user's language and counts the rest", () => {
    expect(announcementSummary(release, false, "sv")).toEqual({
      headlines: ["a sv", "c sv", "d sv"],
      more: 1,
      total: 4
    });
    expect(announcementSummary(release, true, "en")).toEqual({
      headlines: ["a en", "b en", "c en"],
      more: 2,
      total: 5
    });
  });

  it("never reports a negative remainder", () => {
    expect(announcementSummary({ version: "1.0.0", entries: [entry("x")] }, false, "sv")).toEqual({
      headlines: ["x sv"],
      more: 0,
      total: 1
    });
  });
});
