import type { Permission } from "@eneo/eneo-js";
import { describe, expect, test } from "vitest";
import { load } from "./+layout";
import {
  hasOrganizationNavigationPermission,
  resolveOrganizationSkillsAccess
} from "./organizationSkillsAccess";

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
  test("gives Use Skills users the approved catalogue only", async () => {
    await expect(load(eventWithPermissions(["skills"]) as never)).resolves.toEqual({
      canManage: false,
      canPublish: false
    });
  });

  test("gives Skill managers authoring without publication authority", async () => {
    await expect(
      load(eventWithPermissions(["skills", "skills_management"]) as never)
    ).resolves.toEqual({
      canManage: true,
      canPublish: false
    });
  });

  test("gives tenant admins publication authority", async () => {
    await expect(load(eventWithPermissions(["admin"]) as never)).resolves.toEqual({
      canManage: true,
      canPublish: true
    });
  });

  test("rejects direct visits without Skills access", async () => {
    await expect(load(eventWithPermissions([]) as never)).rejects.toMatchObject({
      status: 307,
      location: "/spaces/list"
    });
  });

  test("shows administrators only the reachable organisation workspace destinations", () => {
    const access = resolveOrganizationSkillsAccess({
      admin: true,
      skills: false,
      skillsManagement: false
    });

    expect(hasOrganizationNavigationPermission(access, "read", "skill")).toBe(true);
    expect(hasOrganizationNavigationPermission(access, "read", "website")).toBe(true);
    expect(hasOrganizationNavigationPermission(access, "read", "collection")).toBe(true);
    expect(hasOrganizationNavigationPermission(access, "edit", "space")).toBe(true);
    expect(hasOrganizationNavigationPermission(access, "read", "service")).toBe(false);
    expect(hasOrganizationNavigationPermission(access, "edit", "website")).toBe(false);
  });

  test("limits delegated users to the Skills destination", () => {
    const access = resolveOrganizationSkillsAccess({
      admin: false,
      skills: true,
      skillsManagement: true
    });

    expect(hasOrganizationNavigationPermission(access, "read", "skill")).toBe(true);
    expect(hasOrganizationNavigationPermission(access, "read", "website")).toBe(false);
    expect(hasOrganizationNavigationPermission(access, "read", "collection")).toBe(false);
    expect(hasOrganizationNavigationPermission(access, "edit", "space")).toBe(false);
  });
});
