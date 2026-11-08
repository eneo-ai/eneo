import { describe, expect, test, vi } from "vitest";
import { SKILL_CATALOG_PAGE_SIZE, emptySkillCatalogPage } from "$lib/features/skills/skillCatalog";
import { load } from "./+page";

describe("Skills library loader", () => {
  test("loads only the first bounded catalog page", async () => {
    const page = emptySkillCatalogPage();
    const list = vi.fn().mockResolvedValue(page);
    const event = {
      depends: vi.fn(),
      parent: vi.fn().mockResolvedValue({
        currentSpace: { id: "space-1" },
        eneo: { skills: { list } }
      })
    };

    const result = await load(event as never);

    expect(list).toHaveBeenCalledWith({
      spaceId: "space-1",
      limit: SKILL_CATALOG_PAGE_SIZE
    });
    expect(result.skills).toBe(page);
    expect(result.personalChatSkills).toBeNull();
  });

  test("reads which Skills the personal chat uses in the personal space", async () => {
    const configuration = { bindings: [], runtime: null };
    const getAssistantConfiguration = vi.fn().mockResolvedValue(configuration);
    const event = {
      depends: vi.fn(),
      parent: vi.fn().mockResolvedValue({
        currentSpace: {
          id: "personal-space",
          personal: true,
          default_assistant: { id: "default-assistant" }
        },
        eneo: {
          skills: {
            list: vi.fn().mockResolvedValue(emptySkillCatalogPage()),
            getAssistantConfiguration
          }
        }
      })
    };

    const result = await load(event as never);

    expect(getAssistantConfiguration).toHaveBeenCalledWith({
      spaceId: "personal-space",
      assistantId: "default-assistant"
    });
    expect(result.personalChatSkills).toBe(configuration);
  });
});
