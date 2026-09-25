import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function createEvent(skillPermissions = ["read"]) {
  const skills = [{ id: "skill-1" }];
  const skillRuntimePolicy = { selective_activation_enabled: false };
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
    skills: { catalogue: { list: listSkills } },
    settings: {
      getSkillRuntimePolicy: vi.fn().mockResolvedValue(skillRuntimePolicy)
    }
  };

  return {
    event: {
      depends: vi.fn(),
      parent: vi.fn().mockResolvedValue({ eneo })
    },
    listSkills,
    skills,
    organizationSpace,
    skillRuntimePolicy
  };
}

describe("personal assistant configuration loader", () => {
  test("loads only published organisation Skills for Personal Chat", async () => {
    const { event, listSkills, skills, organizationSpace } = createEvent();

    const result = await load(event as never);

    expect(listSkills).toHaveBeenCalledOnce();
    expect(listSkills).toHaveBeenCalledWith({
      limit: 25,
      cursor: null,
      search: null
    });
    expect(result.skills.items).toEqual(
      skills.map((skill) => ({ ...skill, source: "organization" }))
    );
    expect(result.organizationSpace).toEqual(organizationSpace);
    expect(event.depends).toHaveBeenCalledWith("organization:skills");
  });

  test("loads the tenant Skill runtime policy that gates On demand", async () => {
    const { event, skillRuntimePolicy } = createEvent();

    const result = await load(event as never);

    expect(result.skillRuntimePolicy).toEqual(skillRuntimePolicy);
  });

  test("loads the admin catalogue without a separate Space Skill permission", async () => {
    const { event, listSkills, skills } = createEvent([]);

    const result = await load(event as never);

    expect(listSkills).toHaveBeenCalledOnce();
    expect(result.skills.items).toEqual(
      skills.map((skill) => ({ ...skill, source: "organization" }))
    );
  });
});
