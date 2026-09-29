import { expect, test } from "vitest";
import { readUserUsageQuery, userUsageUrl } from "./usage-query";

const url = new URL(
  "https://eneo.test/admin/usage?tab=tokens&page=7&sortBy=requests&sortOrder=asc&userSearch=anna"
);

test("search resets pagination and retains the global sort", () => {
  const result = readUserUsageQuery(userUsageUrl(url, { search: "  other  " }));
  expect(result).toEqual({
    page: 1,
    perPage: 25,
    sortBy: "requests",
    sortOrder: "asc",
    search: "other"
  });
});
test("pagination preserves the search and selected usage tab", () => {
  const next = userUsageUrl(url, { page: 8 });
  expect(readUserUsageQuery(next)).toMatchObject({ page: 8, search: "anna", sortBy: "requests" });
  expect(next.searchParams.get("tab")).toBe("tokens");
});
test("sorting applies across the result set and resets the page", () => {
  expect(
    readUserUsageQuery(userUsageUrl(url, { sortBy: "username", sortOrder: "desc" }))
  ).toMatchObject({ page: 1, search: "anna", sortBy: "username", sortOrder: "desc" });
});
test("clear search and malformed deep links have safe defaults", () => {
  expect(readUserUsageQuery(userUsageUrl(url, { search: "" }))).toMatchObject({
    page: 1,
    search: ""
  });
  expect(
    readUserUsageQuery(
      new URL("https://eneo.test/admin/usage?page=-1&sortBy=invalid&sortOrder=bad")
    )
  ).toMatchObject({ page: 1, sortBy: "total_tokens", sortOrder: "desc" });
});
