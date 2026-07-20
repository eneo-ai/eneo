import { describe, expect, test, vi } from "vitest";
import { loadSkillBindingCatalog, searchSkillBindingCatalog } from "./skillBindingCatalog";

const local = {
  id: "shared-skill",
  current_revision_id: "draft-revision"
};
const published = {
  id: "shared-skill",
  revision_id: "approved-revision"
};

describe("Skill binding catalog", () => {
  test("combines local and approved Skills with the approved revision winning", async () => {
    const list = vi.fn().mockResolvedValue([local]);
    const catalogueList = vi.fn().mockResolvedValue({ items: [published] });

    const result = await loadSkillBindingCatalog({
      eneo: {
        skills: { list, catalogue: { list: catalogueList } }
      } as never,
      spaceId: "space-1",
      organizationSpace: false
    });

    expect(result).toEqual([published]);
    expect(list).toHaveBeenCalledWith({ spaceId: "space-1" });
    expect(catalogueList).toHaveBeenCalledWith({ limit: 100 });
  });

  test("organization builders never load draft management Skills", async () => {
    const list = vi.fn();
    const catalogueList = vi.fn().mockResolvedValue({ items: [published] });

    const result = await loadSkillBindingCatalog({
      eneo: {
        skills: { list, catalogue: { list: catalogueList } }
      } as never,
      spaceId: "organization-space",
      organizationSpace: true
    });

    expect(result).toEqual([published]);
    expect(list).not.toHaveBeenCalled();
  });

  test("searches the approved catalogue without a separate candidate model", async () => {
    const catalogueList = vi.fn().mockResolvedValue({ items: [published] });
    const eneo = {
      skills: { catalogue: { list: catalogueList } }
    } as never;

    expect(await searchSkillBindingCatalog(eneo, "payroll")).toEqual([published]);
    expect(catalogueList).toHaveBeenCalledWith({
      limit: 100,
      search: "payroll"
    });
  });
});
