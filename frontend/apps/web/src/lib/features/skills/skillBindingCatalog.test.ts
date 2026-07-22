import { describe, expect, test, vi } from "vitest";
import { loadSkillBindingCatalogPage, loadSkillBindingPreview } from "./skillBindingCatalog";

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
  publishedPages = [],
  localRevision,
  publishedDetail
}: {
  localPages?: unknown[];
  publishedPages?: unknown[];
  localRevision?: unknown;
  publishedDetail?: unknown;
}) {
  return {
    skills: {
      list: vi.fn().mockImplementation(() => Promise.resolve(localPages.shift())),
      getRevision: vi.fn().mockResolvedValue(localRevision),
      catalogue: {
        list: vi.fn().mockImplementation(() => Promise.resolve(publishedPages.shift())),
        get: vi.fn().mockResolvedValue(publishedDetail)
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

    expect(result.items).toEqual([{ ...published, source: "organization" }]);
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

    expect(first.items).toEqual([{ ...publishedOnly, source: "organization" }]);
    expect(second.items).toEqual([]);
    expect(third.items).toEqual([{ ...localOnly, source: "space" }]);
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

    expect(result.items).toEqual([{ ...published, source: "organization" }]);
    expect(eneo.skills.list).not.toHaveBeenCalled();
  });

  test("loads an organisation preview through the approved catalogue detail", async () => {
    const detail = {
      id: "published",
      slug: "approved-guidance",
      revision: {
        id: "published-revision-4",
        revision_number: 4,
        display_name: "Approved guidance",
        description: "Approved description",
        instructions: "Approved exact body"
      }
    };
    const eneo = eneoWith({ publishedDetail: detail });
    const candidate = {
      ...published,
      source: "organization" as const
    };

    await expect(
      loadSkillBindingPreview({
        eneo: eneo as never,
        spaceId: "space-1",
        skill: candidate as never
      })
    ).resolves.toEqual({
      id: detail.id,
      source: "organization",
      slug: detail.slug,
      revisionId: detail.revision.id,
      revisionNumber: detail.revision.revision_number,
      displayName: detail.revision.display_name,
      description: detail.revision.description,
      instructions: detail.revision.instructions
    });
    expect(eneo.skills.catalogue.get).toHaveBeenCalledWith({ skillId: candidate.id });
    expect(eneo.skills.getRevision).not.toHaveBeenCalled();
  });

  test("loads a local preview from the candidate's exact revision", async () => {
    const revision = {
      id: "local-revision-2",
      revision_number: 2,
      display_name: "Local guidance",
      description: "Local description",
      instructions: "Local exact body"
    };
    const eneo = eneoWith({ localRevision: revision });
    const candidate = {
      ...local,
      space_id: "space-1",
      slug: "local-guidance",
      current_revision_number: 2,
      display_name: "Local guidance",
      description: "Local description",
      is_active: true,
      content_digest: "local-digest",
      created_by_user_id: "user-1",
      created_at: "2026-07-20T12:00:00Z",
      updated_at: "2026-07-20T12:00:00Z",
      current_revision_id: revision.id,
      source: "space" as const
    };

    await expect(
      loadSkillBindingPreview({
        eneo: eneo as never,
        spaceId: "space-1",
        skill: candidate
      })
    ).resolves.toEqual({
      id: candidate.id,
      source: "space",
      slug: candidate.slug,
      revisionId: revision.id,
      revisionNumber: revision.revision_number,
      displayName: revision.display_name,
      description: revision.description,
      instructions: revision.instructions
    });
    expect(eneo.skills.getRevision).toHaveBeenCalledWith({
      spaceId: "space-1",
      skillId: candidate.id,
      revisionId: revision.id
    });
    expect(eneo.skills.catalogue.get).not.toHaveBeenCalled();
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
