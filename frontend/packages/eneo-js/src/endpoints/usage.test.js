import assert from "node:assert/strict";
import test from "node:test";
import { initUsage } from "./usage.js";

test("usage search and sorting reach the server together with pagination and dates", async () => {
  const api = initUsage({
    fetch: async (endpoint, request) => {
      assert.equal(endpoint, "/api/v1/token-usage/users");
      assert.deepEqual(request.params.query, {
        start_date: "2026-09-01",
        end_date: "2026-10-01",
        page: 2,
        per_page: 25,
        sort_by: "username",
        sort_order: "asc",
        search: "anna"
      });
      return { users: [], total_users: 0 };
    }
  });
  assert.deepEqual(
    await api.tokens.getUsersSummary({
      startDate: "2026-09-01",
      endDate: "2026-10-01",
      page: 2,
      perPage: 25,
      sortBy: "username",
      sortOrder: "asc",
      search: "anna"
    }),
    { users: [], total_users: 0 }
  );
});
