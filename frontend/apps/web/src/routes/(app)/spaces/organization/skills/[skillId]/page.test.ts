import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function event({
  canManage,
  publishedRevisionNumber
}: {
  canManage: boolean;
  publishedRevisionNumber: number | null;
}) {
  const skill = {
    id: "skill-1",
    published_revision_number: publishedRevisionNumber
  };
  const published = { id: "skill-1", revision_number: publishedRevisionNumber ?? 1 };
  const revisionPage = {
    items: [],
    count: 0,
    limit: 25,
    next_cursor: null,
    previous_cursor: null,
    total_count: 0
  };
  const organizationGet = vi.fn().mockResolvedValue(skill);
  const catalogueGet = vi.fn().mockResolvedValue(published);
  const listRevisionSummaries = vi.fn().mockResolvedValue(revisionPage);
  return {
    input: {
      params: { skillId: "skill-1" },
      depends: vi.fn(),
      parent: vi.fn().mockResolvedValue({
        canManage,
        eneo: {
          skills: {
            catalogue: { get: catalogueGet },
            organization: {
              get: organizationGet,
              listRevisionSummaries
            }
          }
        }
      })
    },
    skill,
    published,
    revisionPage,
    organizationGet,
    catalogueGet,
    listRevisionSummaries
  };
}

describe("organisation Skill detail loader", () => {
  test("Use Skills users receive the exact approved version only", async () => {
    const fixture = event({ canManage: false, publishedRevisionNumber: 2 });

    await expect(load(fixture.input as never)).resolves.toEqual({
      mode: "browse",
      published: fixture.published
    });
    expect(fixture.catalogueGet).toHaveBeenCalledWith({ skillId: "skill-1" });
    expect(fixture.organizationGet).not.toHaveBeenCalled();
  });

  test("managers can compare current work with the approved version", async () => {
    const fixture = event({ canManage: true, publishedRevisionNumber: 2 });

    await expect(load(fixture.input as never)).resolves.toEqual({
      mode: "manage",
      skill: fixture.skill,
      revisionPage: fixture.revisionPage,
      published: fixture.published
    });
    expect(fixture.organizationGet).toHaveBeenCalledWith({ skillId: "skill-1" });
    expect(fixture.catalogueGet).toHaveBeenCalledWith({ skillId: "skill-1" });
  });

  test("draft details do not call the published catalogue", async () => {
    const fixture = event({ canManage: true, publishedRevisionNumber: null });

    await expect(load(fixture.input as never)).resolves.toMatchObject({
      mode: "manage",
      published: null
    });
    expect(fixture.catalogueGet).not.toHaveBeenCalled();
  });
});
