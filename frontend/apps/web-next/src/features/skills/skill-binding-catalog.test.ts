import { beforeEach, describe, expect, it, vi } from "vitest";
import { getSkillPreviewForRevision, loadSkillBindingCatalog } from "./skill-binding-catalog";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get } }));
const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });

beforeEach(() => get.mockReset());

describe("Skill binding catalogue", () => {
  it("finishes the approved catalogue before local Skills and keeps the search term", async () => {
    get.mockImplementation(
      (path: string, options: { params?: { query?: { cursor?: string | null } } }) =>
        path === "/api/v1/skills/catalogue/"
          ? ok({
              items: [
                {
                  id: options.params?.query?.cursor ? "published-two" : "published",
                  revision_id: "revision"
                }
              ],
              next_cursor: options.params?.query?.cursor ? null : "more"
            })
          : ok({
              items: [{ id: "local", current_revision_id: "local-revision" }],
              next_cursor: null
            })
    );
    const first = await loadSkillBindingCatalog({
      spaceId: "space",
      organizationSpace: false,
      limit: 1,
      search: "reports"
    });
    expect(first.items.map((skill) => skill.id)).toEqual(["published"]);
    const second = await loadSkillBindingCatalog({
      spaceId: "space",
      organizationSpace: false,
      limit: 1,
      search: "reports",
      cursor: first.next_cursor
    });
    expect(second.items.map((skill) => skill.id)).toEqual(["published-two"]);
    const third = await loadSkillBindingCatalog({
      spaceId: "space",
      organizationSpace: false,
      limit: 1,
      search: "reports",
      cursor: second.next_cursor
    });
    expect(third.items.map((skill) => skill.id)).toEqual(["local"]);
    expect(get).toHaveBeenCalledWith("/api/v1/skills/catalogue/", {
      params: { query: { limit: 1, cursor: "more", search: "reports" } }
    });
  });

  it("fills remaining room with local Skills and avoids duplicates", async () => {
    get.mockImplementation((path: string) =>
      path === "/api/v1/skills/catalogue/"
        ? ok({ items: [{ id: "published", revision_id: "revision" }], next_cursor: null })
        : ok({ items: [{ id: "local", current_revision_id: "local-revision" }], next_cursor: null })
    );
    const page = await loadSkillBindingCatalog({
      spaceId: "space",
      organizationSpace: false,
      limit: 2
    });
    expect(page.items.map((skill) => skill.id)).toEqual(["local", "published"]);
    expect(get).toHaveBeenCalledWith("/api/v1/spaces/{space_id}/skills/", {
      params: { path: { space_id: "space" }, query: { limit: 1, cursor: null, q: undefined } }
    });
  });

  it("never queries local Skills for the organization space", async () => {
    get.mockImplementation(() => ok({ items: [], next_cursor: null }));
    await loadSkillBindingCatalog({ spaceId: "org", organizationSpace: true });
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("rejects a published version that changed after catalogue selection", async () => {
    get.mockImplementation(() => ok({ id: "skill", revision: { id: "newer" } }));
    await expect(
      getSkillPreviewForRevision("space", {
        id: "skill",
        source: "organization",
        revisionId: "selected"
      })
    ).rejects.toThrow("published Skill version changed");
  });
});
