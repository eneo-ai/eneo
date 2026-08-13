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
  });
});
