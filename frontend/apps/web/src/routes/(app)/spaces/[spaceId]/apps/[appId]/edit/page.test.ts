import type { ResourcePermission } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { emptySkillBindingCatalogPage } from "$lib/features/skills/skillBindingCatalog";
import { SKILL_CATALOG_PAGE_SIZE, emptySkillCatalogPage } from "$lib/features/skills/skillCatalog";
import { load } from "./+page";

const READ_SKILL_PERMISSION: ResourcePermission = "read";

describe("App edit loader", () => {
  test("loads Skill bindings for an App reader", async () => {
    const bindings = [{ skill_id: "skill-1" }];
    const listAppBindings = vi.fn().mockResolvedValue(bindings);
    const list = vi.fn().mockResolvedValue(emptySkillCatalogPage());
    const listCatalogue = vi.fn().mockResolvedValue({ items: [], next_cursor: null });
    const event = {
      depends: vi.fn(),
      params: { appId: "app-1" },
      parent: vi.fn().mockResolvedValue({
        currentSpace: {
          id: "space-1",
          organization: false,
          skill_permissions: [READ_SKILL_PERMISSION]
        },
        eneo: {
          apps: { get: vi.fn().mockResolvedValue({ id: "app-1" }) },
          skills: {
            list,
            catalogue: { list: listCatalogue },
            listAppBindings
          }
        }
      })
    };

    const result = await load(event as never);

    expect(listAppBindings).toHaveBeenCalledWith({
      spaceId: "space-1",
      appId: "app-1"
    });
    expect(result.skillBindings).toEqual(bindings);
    expect(list).toHaveBeenCalledWith({
      spaceId: "space-1",
      limit: SKILL_CATALOG_PAGE_SIZE,
      cursor: null,
      query: null
    });
  });

  test("returns an empty catalog without making Skill calls when access is missing", async () => {
    const list = vi.fn();
    const listCatalogue = vi.fn();
    const listAppBindings = vi.fn();
    const event = {
      depends: vi.fn(),
      params: { appId: "app-1" },
      parent: vi.fn().mockResolvedValue({
        currentSpace: {
          id: "space-1",
          organization: false,
          skill_permissions: []
        },
        eneo: {
          apps: { get: vi.fn().mockResolvedValue({ id: "app-1" }) },
          skills: {
            list,
            catalogue: { list: listCatalogue },
            listAppBindings
          }
        }
      })
    };

    const result = await load(event as never);

    expect(result.skills).toEqual(emptySkillBindingCatalogPage());
    expect(result.skillBindings).toEqual([]);
    expect(list).not.toHaveBeenCalled();
    expect(listCatalogue).not.toHaveBeenCalled();
    expect(listAppBindings).not.toHaveBeenCalled();
  });
});
