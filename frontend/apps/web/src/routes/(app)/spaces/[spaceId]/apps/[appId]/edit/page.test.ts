import type { ResourcePermission } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { SKILL_CATALOG_PAGE_SIZE, emptySkillCatalogPage } from "$lib/features/skills/skillCatalog";
import { load } from "./+page";

const READ_SKILL_PERMISSION: ResourcePermission = "read";

describe("App edit loader", () => {
  test("loads Skill bindings for an App reader", async () => {
    const bindings = [{ skill_id: "skill-1" }];
    const listAppBindings = vi.fn().mockResolvedValue(bindings);
    const list = vi.fn().mockResolvedValue(emptySkillCatalogPage());
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
      limit: SKILL_CATALOG_PAGE_SIZE
    });
  });
});
