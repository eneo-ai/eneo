import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function event({ canManage, search = "" }: { canManage: boolean; search?: string }) {
  const cataloguePage = { items: [{ id: "published" }], next_cursor: null };
  const managementPage = { items: [{ id: "draft" }], next_cursor: null };
  const catalogueList = vi.fn().mockResolvedValue(cataloguePage);
  const organizationList = vi.fn().mockResolvedValue(managementPage);
  return {
    input: {
      depends: vi.fn(),
      url: new URL(`https://example.test/spaces/organization/skills?search=${search}`),
      parent: vi.fn().mockResolvedValue({
        canManage,
        eneo: {
          skills: {
            catalogue: { list: catalogueList },
            organization: { list: organizationList }
          }
        }
      })
    },
    catalogueList,
    organizationList,
    cataloguePage,
    managementPage
  };
}

describe("organisation Skills page loader", () => {
  test("Use Skills users receive only the published projection", async () => {
    const fixture = event({ canManage: false, search: " leave " });

    await expect(load(fixture.input as never)).resolves.toEqual({
      mode: "browse",
      page: fixture.cataloguePage,
      search: "leave"
    });
    expect(fixture.catalogueList).toHaveBeenCalledWith({ search: "leave" });
    expect(fixture.organizationList).not.toHaveBeenCalled();
  });

  test("administrators receive publication-aware drafts", async () => {
    const fixture = event({ canManage: true });

    await expect(load(fixture.input as never)).resolves.toEqual({
      mode: "manage",
      page: fixture.managementPage,
      search: ""
    });
    expect(fixture.organizationList).toHaveBeenCalledWith({ search: undefined });
    expect(fixture.catalogueList).not.toHaveBeenCalled();
  });
});
