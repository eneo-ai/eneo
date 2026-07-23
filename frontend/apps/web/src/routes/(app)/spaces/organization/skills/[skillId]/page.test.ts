import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function event({ publishedRevisionNumber }: { publishedRevisionNumber: number | null }) {
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
  const adoptionPage = {
    summary: {
      assistant_count: 0,
      app_count: 0,
      distinct_space_count: 0,
      behind_published_count: 0,
      personal_chat: null,
      revision_counts: []
    },
    items: [],
    limit: 25,
    next_cursor: null
  };
  const organizationGet = vi.fn().mockResolvedValue(skill);
  const catalogueGet = vi.fn().mockResolvedValue(published);
  const listRevisionSummaries = vi.fn().mockResolvedValue(revisionPage);
  const getAdoption = vi.fn().mockResolvedValue(adoptionPage);
  return {
    input: {
      params: { skillId: "skill-1" },
      depends: vi.fn(),
      parent: vi.fn().mockResolvedValue({
        eneo: {
          skills: {
            catalogue: { get: catalogueGet },
            organization: {
              getAdoption,
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
    adoptionPage,
    organizationGet,
    catalogueGet,
    listRevisionSummaries,
    getAdoption
  };
}

describe("organisation Skill detail loader", () => {
  test("managers can compare current work with the approved version", async () => {
    const fixture = event({ publishedRevisionNumber: 2 });

    const result = await load(fixture.input as never);

    expect(result).toMatchObject({
      skill: fixture.skill,
      revisionPage: fixture.revisionPage,
      published: fixture.published
    });
    await expect(result.adoptionPage).resolves.toEqual(fixture.adoptionPage);
    expect(fixture.organizationGet).toHaveBeenCalledWith({ skillId: "skill-1" });
    expect(fixture.catalogueGet).toHaveBeenCalledWith({ skillId: "skill-1" });
    expect(fixture.getAdoption).toHaveBeenCalledWith({ skillId: "skill-1" });
  });

  test("draft details do not call the published catalogue", async () => {
    const fixture = event({ publishedRevisionNumber: null });

    await expect(load(fixture.input as never)).resolves.toMatchObject({
      published: null
    });
    expect(fixture.catalogueGet).not.toHaveBeenCalled();
  });

  test("does not block the core detail while adoption is still loading", async () => {
    const fixture = event({ publishedRevisionNumber: 2 });
    let resolveAdoption!: (value: typeof fixture.adoptionPage) => void;
    const adoptionPage = new Promise<typeof fixture.adoptionPage>((resolve) => {
      resolveAdoption = resolve;
    });
    fixture.getAdoption.mockReturnValue(adoptionPage);

    const result = await load(fixture.input as never);

    expect(result).toMatchObject({
      skill: fixture.skill,
      revisionPage: fixture.revisionPage,
      published: fixture.published
    });
    expect(result.adoptionPage).toBe(adoptionPage);

    resolveAdoption(fixture.adoptionPage);
    await expect(result.adoptionPage).resolves.toEqual(fixture.adoptionPage);
  });

  test("handles an early adoption failure without hiding it from the page", async () => {
    const fixture = event({ publishedRevisionNumber: 2 });
    let resolveSkill!: (value: typeof fixture.skill) => void;
    let rejectAdoption!: (reason: Error) => void;
    const skill = new Promise<typeof fixture.skill>((resolve) => {
      resolveSkill = resolve;
    });
    const adoptionPage = new Promise<typeof fixture.adoptionPage>((_, reject) => {
      rejectAdoption = reject;
    });
    fixture.organizationGet.mockReturnValue(skill);
    fixture.getAdoption.mockReturnValue(adoptionPage);

    const resultPromise = load(fixture.input as never);
    await vi.waitFor(() => expect(fixture.getAdoption).toHaveBeenCalled());

    const failure = new Error("adoption unavailable");
    rejectAdoption(failure);
    await Promise.resolve();
    resolveSkill(fixture.skill);

    const result = await resultPromise;
    expect(result.adoptionPage).toBe(adoptionPage);
    await expect(result.adoptionPage).rejects.toBe(failure);
  });

  test("handles an early revision failure while preserving the Skill failure", async () => {
    const fixture = event({ publishedRevisionNumber: 2 });
    let rejectSkill!: (reason: Error) => void;
    let rejectRevisionPage!: (reason: Error) => void;
    const skill = new Promise<typeof fixture.skill>((_, reject) => {
      rejectSkill = reject;
    });
    const revisionPage = new Promise<typeof fixture.revisionPage>((_, reject) => {
      rejectRevisionPage = reject;
    });
    fixture.organizationGet.mockReturnValue(skill);
    fixture.listRevisionSummaries.mockReturnValue(revisionPage);

    const unhandledRejection = vi.fn();
    process.on("unhandledRejection", unhandledRejection);
    try {
      const resultPromise = load(fixture.input as never);
      await vi.waitFor(() => expect(fixture.listRevisionSummaries).toHaveBeenCalled());

      rejectRevisionPage(new Error("revision summaries unavailable"));
      await new Promise((resolve) => setTimeout(resolve, 0));

      const skillFailure = new Error("Skill unavailable");
      rejectSkill(skillFailure);
      await expect(resultPromise).rejects.toBe(skillFailure);
      await new Promise((resolve) => setTimeout(resolve, 0));

      expect(unhandledRejection).not.toHaveBeenCalled();
    } finally {
      process.off("unhandledRejection", unhandledRejection);
    }
  });
});
