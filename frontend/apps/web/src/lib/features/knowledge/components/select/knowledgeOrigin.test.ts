import { describe, expect, test } from "vitest";
import { isOrgItem, isPersonalItem, ownerSpaceId, partitionByOrigin } from "./knowledgeOrigin";

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

describe("isPersonalItem", () => {
  test("unowned items are personal", () => {
    expect(isPersonalItem({}, "current")).toBe(true);
  });
  test("items owned by the current space are personal", () => {
    expect(isPersonalItem({ space_id: "current" }, "current")).toBe(true);
  });
  test("items owned by another space are not personal", () => {
    expect(isPersonalItem({ space_id: "other" }, "current")).toBe(false);
  });
});

describe("isOrgItem", () => {
  test("matches the configured org space when one is set", () => {
    expect(isOrgItem({ space_id: "org" }, "current", "org")).toBe(true);
    expect(isOrgItem({ space_id: "other" }, "current", "org")).toBe(false);
  });
  test("without an org space, any owned non-current space counts as org", () => {
    expect(isOrgItem({ space_id: "other" }, "current", undefined)).toBe(true);
    expect(isOrgItem({ space_id: "current" }, "current", undefined)).toBe(false);
    expect(isOrgItem({}, "current", undefined)).toBe(false);
  });
  test("without a current space and no org space, nothing is org", () => {
    expect(isOrgItem({ space_id: "x" }, undefined, undefined)).toBe(false);
  });
});

describe("partitionByOrigin", () => {
  test("splits unowned/current into personal and the rest into org", () => {
    const { personal, org } = partitionByOrigin(
      [{ space_id: "current" }, {}, { space_id: "other" }, { space: { id: "current" } }],
      "current"
    );
    expect(personal).toHaveLength(3);
    expect(org).toHaveLength(1);
    expect(ownerSpaceId(org[0])).toBe("other");
  });
});
