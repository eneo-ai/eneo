import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function createEvent(skillPermissions = ["read"]) {
  const skills = [{ id: "skill-1" }];
  const organizationSpace = {
    id: "organization-space",
    skill_permissions: skillPermissions
  };
  const listSkills = vi.fn().mockResolvedValue({
    items: skills,
    next_cursor: null
  });
  const eneo = {
    governancePolicy: { get: vi.fn().mockResolvedValue({}) },
    models: { list: vi.fn().mockResolvedValue({}) },
    mcpServers: { listSettings: vi.fn().mockResolvedValue({}) },
    promptLibrary: { list: vi.fn().mockResolvedValue({}) },
    modelProviders: { list: vi.fn().mockResolvedValue([]) },
    spaces: { getOrganizationSpace: vi.fn().mockResolvedValue(organizationSpace) },
    skills: { catalogue: { list: listSkills } }
  };

  return {
    event: {
      depends: vi.fn(),
      parent: vi.fn().mockResolvedValue({ eneo })
    },
    listSkills,
    skills,
    organizationSpace
  };
}

describe("personal assistant configuration loader", () => {
  test("loads only published organisation Skills for Personal Chat", async () => {
    const { event, listSkills, skills, organizationSpace } = createEvent();

    const result = await load(event as never);

    expect(listSkills).toHaveBeenCalledOnce();
    expect(listSkills).toHaveBeenCalledWith({ limit: 100 });
    expect(result.skills).toEqual(skills);
    expect(result.organizationSpace).toEqual(organizationSpace);
    expect(event.depends).toHaveBeenCalledWith("organization:skills");
  });

  test("does not load catalogue entries without Skill use permission", async () => {
    const { event, listSkills } = createEvent([]);

    const result = await load(event as never);

    expect(listSkills).not.toHaveBeenCalled();
    expect(result.skills).toEqual([]);
  });
});
