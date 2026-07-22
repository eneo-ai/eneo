import type { ResourcePermission } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { SKILL_CATALOG_PAGE_SIZE, emptySkillCatalogPage } from "$lib/features/skills/skillCatalog";
import { load } from "./+page";

const READ_SKILL_PERMISSION: ResourcePermission = "read";

function createEvent(skillPermissions: ResourcePermission[]) {
  const skills = { ...emptySkillCatalogPage(), items: [{ id: "skill-1" }], total_count: 1 };
  const listSkills = vi.fn().mockResolvedValue(skills);
  const eneo = {
    governancePolicy: { get: vi.fn().mockResolvedValue({}) },
    models: { list: vi.fn().mockResolvedValue({}) },
    mcpServers: { listSettings: vi.fn().mockResolvedValue({}) },
    promptLibrary: { list: vi.fn().mockResolvedValue({}) },
    modelProviders: { list: vi.fn().mockResolvedValue([]) },
    spaces: {
      getOrganizationSpace: vi.fn().mockResolvedValue({
        id: "organization-space",
        skill_permissions: skillPermissions
      })
    },
    skills: { list: listSkills }
  };

  return {
    event: {
      depends: vi.fn(),
      parent: vi.fn().mockResolvedValue({ eneo })
    },
    listSkills,
    skills
  };
}

describe("personal assistant configuration loader", () => {
  test("keeps the governance page available when Skills cannot be read", async () => {
    const { event, listSkills } = createEvent([]);

    const result = await load(event as never);

    expect(listSkills).not.toHaveBeenCalled();
    expect(result.skills).toEqual(emptySkillCatalogPage());
    expect(event.depends).toHaveBeenCalledWith("admin:governance-policy");
  });

  test("loads the Skills facet when the generated Space permission allows it", async () => {
    const { event, listSkills, skills } = createEvent([READ_SKILL_PERMISSION]);

    const result = await load(event as never);

    expect(listSkills).toHaveBeenCalledOnce();
    expect(listSkills).toHaveBeenCalledWith({
      spaceId: "organization-space",
      limit: SKILL_CATALOG_PAGE_SIZE
    });
    expect(result.skills).toEqual(skills);
  });
});
