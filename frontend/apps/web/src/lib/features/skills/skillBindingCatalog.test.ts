import { describe, expect, test, vi } from "vitest";
import { loadSkillBindingCatalogPage } from "./skillBindingCatalog";

const local = {
  id: "shared-skill",
  current_revision_id: "draft-revision"
};
const published = {
  id: "shared-skill",
  revision_id: "approved-revision"
};

function eneoWith({
  localPages = [],
  publishedPages = []
}: {
  localPages?: unknown[];
  publishedPages?: unknown[];
}) {
  return {
    skills: {
      list: vi.fn().mockImplementation(() => Promise.resolve(localPages.shift())),
      catalogue: {
        list: vi.fn().mockImplementation(() => Promise.resolve(publishedPages.shift()))
      }
    }
  };
}

describe("Skill binding catalog", () => {
  test("combines bounded approved and local pages with the approved revision winning", async () => {
    const eneo = eneoWith({
      publishedPages: [{ items: [published], next_cursor: null }],
      localPages: [{ items: [local], next_cursor: null }]
    });

    const result = await loadSkillBindingCatalogPage({
      eneo: eneo as never,
      spaceId: "space-1",
      organizationSpace: false,
      limit: 2
    });

    expect(result.items).toEqual([published]);
    expect(result.count).toBe(1);
    expect(result.next_cursor).toBeNull();
    expect(eneo.skills.catalogue.list).toHaveBeenCalledWith({
      limit: 2,
      cursor: null,
      search: null
    });
    expect(eneo.skills.list).toHaveBeenCalledWith({
      spaceId: "space-1",
      limit: 1,
      cursor: null,
      query: null
    });
  });

  test("continues into local Skills without a fixed catalogue-size cap", async () => {
    const publishedOnly = { ...published, id: "published" };
    const localOnly = { ...local, id: "local" };
    const eneo = eneoWith({
      publishedPages: [{ items: [publishedOnly], next_cursor: null }],
      localPages: [
        { items: [], next_cursor: "local-next" },
        { items: [localOnly], next_cursor: null }
      ]
    });

    const first = await loadSkillBindingCatalogPage({
      eneo: eneo as never,
      spaceId: "space-1",
      organizationSpace: false,
      limit: 1,
      query: " payroll "
    });
    const second = await loadSkillBindingCatalogPage({
      eneo: eneo as never,
      spaceId: "space-1",
      organizationSpace: false,
      limit: 1,
      cursor: first.next_cursor,
      query: "payroll"
    });
    const third = await loadSkillBindingCatalogPage({
      eneo: eneo as never,
      spaceId: "space-1",
      organizationSpace: false,
      limit: 1,
      cursor: second.next_cursor,
      query: "payroll"
    });

    expect(first.items).toEqual([publishedOnly]);
    expect(second.items).toEqual([]);
    expect(third.items).toEqual([localOnly]);
    expect(eneo.skills.catalogue.list).toHaveBeenCalledTimes(1);
    expect(eneo.skills.list).toHaveBeenNthCalledWith(1, {
      spaceId: "space-1",
      limit: 1,
      cursor: null,
      query: "payroll"
    });
    expect(eneo.skills.list).toHaveBeenNthCalledWith(2, {
      spaceId: "space-1",
      limit: 1,
      cursor: "local-next",
      query: "payroll"
    });
  });

  test("organization builders load only the published catalogue", async () => {
    const eneo = eneoWith({
      publishedPages: [{ items: [published], next_cursor: null }]
    });

    const result = await loadSkillBindingCatalogPage({
      eneo: eneo as never,
      spaceId: "organization-space",
      organizationSpace: true
    });

    expect(result.items).toEqual([published]);
    expect(eneo.skills.list).not.toHaveBeenCalled();
  });

  test("rejects a corrupted continuation cursor without making requests", async () => {
    const eneo = eneoWith({});

    await expect(
      loadSkillBindingCatalogPage({
        eneo: eneo as never,
        spaceId: "space-1",
        organizationSpace: false,
        cursor: "not-a-cursor"
      })
    ).rejects.toThrow("Invalid Skill catalogue cursor");

    expect(eneo.skills.catalogue.list).not.toHaveBeenCalled();
    expect(eneo.skills.list).not.toHaveBeenCalled();
  });
});
