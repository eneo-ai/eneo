import type { ResourcePermission } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { SKILL_CATALOG_PAGE_SIZE, emptySkillCatalogPage } from "$lib/features/skills/skillCatalog";
import { load } from "./+page";

const READ_SKILL_PERMISSION: ResourcePermission = "read";

describe("Assistant edit loader", () => {
  test("loads Skill bindings for a reader of a non-default Assistant", async () => {
    const bindings = [{ skill_id: "skill-1" }];
    const listAssistantBindings = vi.fn().mockResolvedValue(bindings);
    const event = {
      depends: vi.fn(),
      params: { assistantId: "assistant-1" },
      parent: vi.fn().mockResolvedValue({
        currentSpace: {
          id: "space-1",
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
            list: vi.fn().mockResolvedValue(emptySkillCatalogPage()),
            listAssistantBindings
          }
        }
      })
    };

    const result = await load(event as never);

    expect(listAssistantBindings).toHaveBeenCalledWith({
      spaceId: "space-1",
      assistantId: "assistant-1"
    });
    expect(result.skillBindings).toEqual(bindings);
  });

  test("keeps direct Skills disabled for the personal default Assistant", async () => {
    const list = vi.fn();
    const listAssistantBindings = vi.fn();
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
          skills: { list, listAssistantBindings }
        }
      })
    };

    const result = await load(event as never);

    expect(result.supportsDirectSkills).toBe(false);
    expect(result.skills).toEqual(emptySkillCatalogPage());
    expect(result.skillBindings).toEqual([]);
    expect(list).not.toHaveBeenCalled();
    expect(listAssistantBindings).not.toHaveBeenCalled();
  });

  test("loads direct Skills for a shared default Assistant", async () => {
    const skills = { ...emptySkillCatalogPage(), items: [{ id: "skill-1" }], total_count: 1 };
    const bindings = [{ skill_id: "skill-1" }];
    const list = vi.fn().mockResolvedValue(skills);
    const listAssistantBindings = vi.fn().mockResolvedValue(bindings);
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
          skills: { list, listAssistantBindings }
        }
      })
    };

    const result = await load(event as never);

    expect(result.supportsDirectSkills).toBe(true);
    expect(result.skills).toEqual(skills);
    expect(result.skillBindings).toEqual(bindings);
    expect(list).toHaveBeenCalledWith({
      spaceId: "shared-space",
      limit: SKILL_CATALOG_PAGE_SIZE
    });
    expect(listAssistantBindings).toHaveBeenCalledWith({
      spaceId: "shared-space",
      assistantId: "default-assistant"
    });
  });
});
