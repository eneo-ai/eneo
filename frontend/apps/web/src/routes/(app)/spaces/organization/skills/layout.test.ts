import type { Permission } from "@eneo/eneo-js";
import { describe, expect, test } from "vitest";
import { load } from "./+layout";

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
});
