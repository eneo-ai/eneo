import { describe, expect, test } from "vitest";
import { readUserQuery, userQueryString } from "./user-query";

describe("admin user navigation", () => {
  const query = readUserQuery(
    new URL(
      "https://eneo.test/admin/users?tab=active&page=90&search=anna&search_name=smith&role_id=role-1"
    )
  );

  test("switching to inactive performs a new request with the same filters on page one", () => {
    const next = userQueryString(query, { tab: "inactive" });
    expect(next).toBe("?tab=inactive&search=anna&search_name=smith&role_id=role-1");
    expect(readUserQuery(new URL(next, "https://eneo.test/admin/users"))).toEqual({
      ...query,
      tab: "inactive",
      page: 1
    });
  });

  test("page links retain all filters", () => {
    expect(userQueryString(query, { page: 91 })).toBe(
      "?tab=active&search=anna&search_name=smith&role_id=role-1&page=91"
    );
  });

  test("clearing filters keeps the selected status and resets pagination", () => {
    expect(
      userQueryString({ ...query, tab: "inactive" }, { search: "", searchName: "", roleId: "" })
    ).toBe("?tab=inactive");
  });

  test.each(["0", "-1", "1.5", "invalid", "Infinity"])(
    "invalid page %s starts at page one",
    (page) => {
      expect(readUserQuery(new URL(`https://eneo.test/admin/users?page=${page}`)).page).toBe(1);
    }
  );

  test("deep links respect the API depth limit", () => {
    expect(readUserQuery(new URL("https://eneo.test/admin/users?page=101")).page).toBe(100);
  });

  test("existing email-search links keep working and become canonical", () => {
    const legacy = readUserQuery(new URL("https://eneo.test/admin/users?search_email=%20anna%20"));
    expect(userQueryString(legacy)).toBe("?tab=active&search=anna");
  });
});
