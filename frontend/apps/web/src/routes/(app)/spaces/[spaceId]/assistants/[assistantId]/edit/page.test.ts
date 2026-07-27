import type { ResourcePermission } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { emptySkillBindingCatalogPage } from "$lib/features/skills/skillBindingCatalog";
import { SKILL_CATALOG_PAGE_SIZE, emptySkillCatalogPage } from "$lib/features/skills/skillCatalog";
import { load } from "./+page";

const READ_SKILL_PERMISSION: ResourcePermission = "read";

describe("Assistant edit loader", () => {
  test("loads Skill bindings for a reader of a non-default Assistant", async () => {
    const configuration = {
      bindings: [
        {
          skill_id: "skill-1",
          skill_revision_id: "revision-1",
          activation_mode: "on_demand"
        }
      ],
      runtime: {
        effective_model_id: "model-1",
        effective_mode: "selective",
        fallback_reason: null,
        skill_context_tokens: 100,
        skill_context_token_limit: 800,
        token_count_source: "litellm"
      }
    };
    const skills = emptySkillBindingCatalogPage();
    const listSkills = vi.fn().mockResolvedValue(emptySkillCatalogPage());
    const listCatalogue = vi.fn().mockResolvedValue({ items: [], next_cursor: null });
    const getAssistantConfiguration = vi.fn().mockResolvedValue(configuration);
    const event = {
      depends: vi.fn(),
      params: { assistantId: "assistant-1" },
      parent: vi.fn().mockResolvedValue({
        currentSpace: {
          id: "space-1",
          organization: false,
          default_assistant: { id: "default-assistant" },
          skill_permissions: [READ_SKILL_PERMISSION]
        },
        eneo: {
          assistants: {
            get: vi.fn().mockResolvedValue({ id: "assistant-1" }),
            listMCPServers: vi.fn().mockResolvedValue({ items: [] })
          },
          helpAssistants: {
            runs: { availability: vi.fn().mockResolvedValue(null) }
          },
          skills: {
            list: listSkills,
            catalogue: { list: listCatalogue },
            getAssistantConfiguration
          }
        }
      })
    };

    const result = await load(event as never);

    expect(getAssistantConfiguration).toHaveBeenCalledWith({
      spaceId: "space-1",
      assistantId: "assistant-1"
    });
    expect(result.skillBindings).toEqual(configuration.bindings);
    expect(result.skillRuntime).toEqual(configuration.runtime);
    expect(result.skills).toEqual(skills);
    expect(listSkills).toHaveBeenCalledWith({
      spaceId: "space-1",
      limit: SKILL_CATALOG_PAGE_SIZE,
      cursor: null,
      query: null
    });
  });

  test("keeps direct Skills disabled for the personal default Assistant", async () => {
    const list = vi.fn();
    const getAssistantConfiguration = vi.fn();
    const event = {
      depends: vi.fn(),
      params: { assistantId: "default-assistant" },
      parent: vi.fn().mockResolvedValue({
        currentSpace: {
          id: "personal-space",
          personal: true,
          default_assistant: { id: "default-assistant" },
          skill_permissions: [READ_SKILL_PERMISSION]
        },
        eneo: {
          assistants: {
            get: vi.fn().mockResolvedValue({ id: "default-assistant" }),
            listMCPServers: vi.fn().mockResolvedValue({ items: [] })
          },
          helpAssistants: {
            runs: { availability: vi.fn().mockResolvedValue(null) }
          },
          skills: { list, getAssistantConfiguration }
        }
      })
    };

    const result = await load(event as never);

    expect(result.supportsDirectSkills).toBe(false);
    expect(result.skills).toEqual(emptySkillBindingCatalogPage());
    expect(result.skillBindings).toEqual([]);
    expect(result.skillRuntime).toBeNull();
    expect(list).not.toHaveBeenCalled();
    expect(getAssistantConfiguration).not.toHaveBeenCalled();
  });

  test("loads direct Skills for a shared default Assistant", async () => {
    const localSkills = {
      ...emptySkillCatalogPage(),
      items: [{ id: "skill-1" }],
      total_count: 1
    };
    const skills = {
      ...emptySkillBindingCatalogPage(),
      items: localSkills.items.map((skill) => ({ ...skill, source: "space" as const })),
      count: 1
    };
    const configuration = {
      bindings: [
        {
          skill_id: "skill-1",
          skill_revision_id: "revision-1",
          activation_mode: "always"
        }
      ],
      runtime: null
    };
    const list = vi.fn().mockResolvedValue(localSkills);
    const listCatalogue = vi.fn().mockResolvedValue({ items: [], next_cursor: null });
    const getAssistantConfiguration = vi.fn().mockResolvedValue(configuration);
    const event = {
      depends: vi.fn(),
      params: { assistantId: "default-assistant" },
      parent: vi.fn().mockResolvedValue({
        currentSpace: {
          id: "shared-space",
          personal: false,
          default_assistant: { id: "default-assistant" },
          skill_permissions: [READ_SKILL_PERMISSION]
        },
        eneo: {
          assistants: {
            get: vi.fn().mockResolvedValue({ id: "default-assistant" }),
            listMCPServers: vi.fn().mockResolvedValue({ items: [] })
          },
          helpAssistants: {
            runs: { availability: vi.fn().mockResolvedValue(null) }
          },
          skills: {
            list,
            catalogue: { list: listCatalogue },
            getAssistantConfiguration
          }
        }
      })
    };

    const result = await load(event as never);

    expect(result.supportsDirectSkills).toBe(true);
    expect(result.skills).toEqual(skills);
    expect(result.skillBindings).toEqual(configuration.bindings);
    expect(result.skillRuntime).toBeNull();
    expect(list).toHaveBeenCalledWith({
      spaceId: "shared-space",
      limit: SKILL_CATALOG_PAGE_SIZE,
      cursor: null,
      query: null
    });
    expect(getAssistantConfiguration).toHaveBeenCalledWith({
      spaceId: "shared-space",
      assistantId: "default-assistant"
    });
  });
});
