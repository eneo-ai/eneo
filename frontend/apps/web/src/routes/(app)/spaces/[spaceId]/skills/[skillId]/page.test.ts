import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

describe("Skill detail loader", () => {
  test("seeds the page with one bounded revision-summary page", async () => {
    const skill = { id: "skill-1" };
    const revisionPage = {
      items: [],
      count: 0,
      limit: 25,
      next_cursor: null,
      previous_cursor: null,
      total_count: 0
    };
    const get = vi.fn(async () => skill);
    const listRevisionSummaries = vi.fn(async () => revisionPage);
    const depends = vi.fn();

    const result = await load({
      params: { skillId: "skill-1" },
      depends,
      parent: async () => ({
        eneo: { skills: { get, listRevisionSummaries } },
        currentSpace: { id: "space-1" }
      })
    } as never);

    expect(depends).toHaveBeenCalledWith("space:skills");
    expect(get).toHaveBeenCalledWith({
      spaceId: "space-1",
      skillId: "skill-1"
    });
    expect(listRevisionSummaries).toHaveBeenCalledWith({
      spaceId: "space-1",
      skillId: "skill-1"
    });
    expect(result).toEqual({ skill, revisionPage });
  });
});
