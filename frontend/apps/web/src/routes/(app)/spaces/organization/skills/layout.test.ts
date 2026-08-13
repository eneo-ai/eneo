import type { Permission } from "@eneo/eneo-js";
import { describe, expect, test } from "vitest";
import { load } from "./+layout";
import { hasOrganizationNavigationPermission } from "./organizationSkillsAccess";

function eventWithPermissions(permissions: Permission[]) {
  return {
    parent: async () => ({
      user: {
        roles: [{ permissions }]
      }
    })
  };
}

describe("organisation Skills layout", () => {
  test("does not expose the organisation workspace to Use Skills users", async () => {
    await expect(load(eventWithPermissions(["skills"]) as never)).rejects.toMatchObject({
      status: 307,
      location: "/spaces/list"
    });
  });

  test("does not expose organisation authoring to delegated Skill managers", async () => {
    await expect(
      load(eventWithPermissions(["skills", "skills_management"]) as never)
    ).rejects.toMatchObject({
      status: 307,
      location: "/spaces/list"
    });
  });

  test("gives tenant admins publication authority", async () => {
    await expect(load(eventWithPermissions(["admin"]) as never)).resolves.toBeUndefined();
  });

  test("rejects direct visits without Skills access", async () => {
    await expect(load(eventWithPermissions([]) as never)).rejects.toMatchObject({
      status: 307,
      location: "/spaces/list"
    });
  });

  test("shows administrators only the reachable organisation workspace destinations", () => {
    expect(hasOrganizationNavigationPermission(true, "read", "skill")).toBe(true);
    expect(hasOrganizationNavigationPermission(true, "read", "website")).toBe(true);
    expect(hasOrganizationNavigationPermission(true, "read", "collection")).toBe(true);
    expect(hasOrganizationNavigationPermission(true, "edit", "space")).toBe(true);
    expect(hasOrganizationNavigationPermission(true, "read", "service")).toBe(false);
    expect(hasOrganizationNavigationPermission(true, "edit", "website")).toBe(false);
  });

  test("does not project organisation navigation for delegated users", () => {
    expect(hasOrganizationNavigationPermission(false, "read", "skill")).toBe(false);
    expect(hasOrganizationNavigationPermission(false, "read", "website")).toBe(false);
    expect(hasOrganizationNavigationPermission(false, "read", "collection")).toBe(false);
    expect(hasOrganizationNavigationPermission(false, "edit", "space")).toBe(false);
  });
});
