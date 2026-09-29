import assert from "node:assert/strict";
import test from "node:test";
import { initUser } from "./users.js";

test("admin listing sends combined filters and preserves pagination metadata", async () => {
  const calls = [];
  const response = {
    items: [{ id: "inactive-user", state: "inactive" }],
    metadata: { page: 2, total_count: 150, counts: { active: 10, inactive: 150 } }
  };
  const users = initUser({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return response;
    }
  });
  assert.equal(
    await users.list({
      includeDetails: true,
      page: 2,
      page_size: 100,
      search_email: "@example.com",
      search_name: "anna",
      state_filter: "inactive",
      role_id: "role-1"
    }),
    response
  );
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/users/",
      request: {
        method: "get",
        params: {
          query: {
            page: 2,
            page_size: 100,
            search_email: "@example.com",
            search_name: "anna",
            state_filter: "inactive",
            role_id: "role-1"
          }
        }
      }
    }
  ]);
});

test("member picker keeps the sparse cursor-based listing contract", async () => {
  const users = initUser({
    fetch: async (endpoint, request) => {
      assert.equal(endpoint, "/api/v1/users/");
      assert.deepEqual(request.params.query, { email: "anna", limit: 25, cursor: "next" });
      return { items: [], next_cursor: null, total_count: 0 };
    }
  });
  assert.deepEqual(await users.list({ filter: "anna", limit: 25, cursor: "next" }), {
    items: [],
    next_cursor: null,
    total_count: 0
  });
});
