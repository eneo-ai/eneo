import { describe, expect, test } from "vitest";
import { classifyKnowledgeOrigin, ownerSpaceId, partitionByOrigin } from "./knowledgeOrigin";

describe("ownerSpaceId", () => {
  test("reads the space id from any of the supported shapes", () => {
    expect(ownerSpaceId({ space_id: "a" })).toBe("a");
    expect(ownerSpaceId({ spaceId: "b" })).toBe("b");
    expect(ownerSpaceId({ space: { id: "c" } })).toBe("c");
    expect(ownerSpaceId({ metadata: { space_id: "d" } })).toBe("d");
    expect(ownerSpaceId({ metadata: { spaceId: "e" } })).toBe("e");
    expect(ownerSpaceId({})).toBeUndefined();
    expect(ownerSpaceId(null)).toBeUndefined();
  });
});

describe("classifyKnowledgeOrigin", () => {
  test("uses ownership for current-space, organization and shared sources", () => {
    expect(classifyKnowledgeOrigin({ space_id: "current" }, "current", "org")).toBe("space");
    expect(classifyKnowledgeOrigin({ space_id: "org" }, "current", "org")).toBe("organization");
    expect(classifyKnowledgeOrigin({ space_id: "other" }, "current", "org")).toBe("shared");
  });
  test("does not guess organization ownership when its identity is unavailable", () => {
    expect(classifyKnowledgeOrigin({ space_id: "other" }, "current", undefined)).toBe("shared");
    expect(classifyKnowledgeOrigin({ space_id: "org" }, "current", undefined)).toBe("shared");
  });
  test("keeps sources without ownership in the current-space section", () => {
    expect(classifyKnowledgeOrigin({}, "current", "org")).toBe("space");
    expect(classifyKnowledgeOrigin({ space_id: null }, undefined, undefined)).toBe("space");
  });
  test("keeps owned sources visible even before current-space identity is available", () => {
    expect(classifyKnowledgeOrigin({ space_id: "other" }, undefined, undefined)).toBe("shared");
    expect(classifyKnowledgeOrigin({ space_id: "org" }, undefined, "org")).toBe("organization");
  });
  test("the organization's own sources belong to the current section when editing its space", () => {
    expect(classifyKnowledgeOrigin({ space_id: "org" }, "org", "org")).toBe("space");
  });
});

describe("partitionByOrigin", () => {
  test.each(["org", undefined])(
    "every source appears exactly once with org identity %s",
    (orgId) => {
      const items = [
        { id: "local", space_id: "current" },
        { id: "organization", space_id: "org" },
        { id: "shared", space_id: "other" },
        { id: "unowned" }
      ];
      const partitions = partitionByOrigin(items, "current", orgId);
      const displayedIds = Object.values(partitions)
        .flat()
        .map((item) => item.id);
      expect(displayedIds.sort()).toEqual(items.map((item) => item.id).sort());
      expect(partitions.shared.map((item) => item.id)).toContain("shared");
      expect(partitions.organization.map((item) => item.id)).toEqual(orgId ? ["organization"] : []);
    }
  );
  test("preserves source order within each origin", () => {
    const first = { space_id: "other", id: "first" };
    const second = { space_id: "other", id: "second" };
    expect(
      partitionByOrigin([first, { space_id: "current" }, second], "current", "org").shared
    ).toEqual([first, second]);
  });
});
