import { describe, expect, it } from "vitest";
import { readUsersFilters, usersFiltersSearchParams } from "./users";

describe("admin users URL filters", () => {
  it("reads and serializes the shared view used by page and route", () => {
    const params = new URLSearchParams(
      "tab=inactive&search=kommun&search_name=anna&page=3&role_id=custom"
    );
    const filters = readUsersFilters(params);
    expect(filters).toEqual({
      stateFilter: "inactive",
      search: "kommun",
      searchName: "anna",
      page: 3,
      roleId: "custom"
    });
    expect(usersFiltersSearchParams(filters).toString()).toBe(params.toString());
    expect(usersFiltersSearchParams(readUsersFilters(new URLSearchParams())).toString()).toBe("");
  });

  it.each(["1.5", "Infinity", "9007199254740992"])("defaults an invalid page %s", (page) => {
    expect(readUsersFilters(new URLSearchParams({ page, tab: "unknown" }))).toMatchObject({
      page: 1,
      stateFilter: "active"
    });
  });
});
