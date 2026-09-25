import type { ResourcePermission } from "@eneo/eneo-js";
import { describe, expect, test } from "vitest";
import { load } from "./+page";

const CREATE_SKILL_PERMISSION: ResourcePermission = "create";
const READ_SKILL_PERMISSION: ResourcePermission = "read";

function eventWithPermissions(skillPermissions: ResourcePermission[]) {
  return {
    parent: async () => ({
      currentSpace: {
        id: "space-1",
        personal: false,
        organization: false,
        skill_permissions: skillPermissions
      }
    })
  };
}

describe("new Skill loader", () => {
  test("allows the create page only with the generated Space permission", async () => {
    await expect(
      load(eventWithPermissions([CREATE_SKILL_PERMISSION]) as never)
    ).resolves.toBeUndefined();
  });

  test("redirects a read-only direct visit to the Skill library", async () => {
    await expect(
      load(eventWithPermissions([READ_SKILL_PERMISSION]) as never)
    ).rejects.toMatchObject({
      status: 307,
      location: "/spaces/space-1/skills"
    });
  });

  test("redirects a visit without Skills access to the Space overview", async () => {
    await expect(load(eventWithPermissions([]) as never)).rejects.toMatchObject({
      status: 307,
      location: "/spaces/space-1/overview"
    });
  });
});
