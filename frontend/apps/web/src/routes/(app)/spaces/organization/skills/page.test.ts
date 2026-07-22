import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function event({ search = "" }: { search?: string } = {}) {
  const managementPage = { items: [{ id: "draft" }], next_cursor: null };
  const organizationList = vi.fn().mockResolvedValue(managementPage);
  return {
    input: {
      depends: vi.fn(),
      url: new URL(`https://example.test/spaces/organization/skills?search=${search}`),
      parent: vi.fn().mockResolvedValue({
        eneo: {
          skills: {
            organization: { list: organizationList }
          }
        }
      })
    },
    organizationList,
    managementPage
  };
}

describe("organisation Skills page loader", () => {
  test("administrators receive publication-aware drafts", async () => {
    const fixture = event({ search: " leave " });

    await expect(load(fixture.input as never)).resolves.toEqual({
      page: fixture.managementPage,
      search: "leave"
    });
    expect(fixture.organizationList).toHaveBeenCalledWith({ search: "leave" });
  });
});
