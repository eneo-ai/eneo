import assert from "node:assert/strict";
import test from "node:test";

import { initWebsites } from "./websites.js";

test("cancel crawl run uses the typed crawl lifecycle endpoint", async () => {
  const calls = [];
  const websites = initWebsites({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { id: "crawl-run-id" };
    }
  });

  const result = await websites.crawlRuns.cancel({ id: "crawl-run-id" });

  assert.deepEqual(result, { id: "crawl-run-id" });
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/crawl-runs/{id}/cancel/",
      request: {
        method: "post",
        params: { path: { id: "crawl-run-id" } }
      }
    }
  ]);
});

test("indexed content listing preserves its array response", async () => {
  const calls = [];
  const items = [{ id: "blob-1" }, { id: "blob-2" }];
  const websites = initWebsites({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { items, count: items.length };
    }
  });

  const result = await websites.indexedBlobs.list({ id: "website-id" });

  assert.equal(result, items);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/websites/{id}/info-blobs/",
      request: {
        method: "get",
        params: { path: { id: "website-id" } }
      }
    }
  ]);
});

test("indexed content page exposes its bounded cursor response", async () => {
  const calls = [];
  const page = {
    items: [{ id: "blob-2" }],
    count: 1,
    total_count: 3,
    limit: 2,
    next_cursor: "blob-2",
    previous_cursor: null
  };
  const websites = initWebsites({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return page;
    }
  });

  const result = await websites.indexedBlobs.listPage({
    id: "website-id",
    limit: 2,
    cursor: "blob-1"
  });

  assert.equal(result, page);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/websites/{id}/info-blobs/page/",
      request: {
        method: "get",
        params: {
          path: { id: "website-id" },
          query: { limit: 2, cursor: "blob-1" }
        }
      }
    }
  ]);
});

test("bulk stop sends website IDs to the bounded stop endpoint", async () => {
  const calls = [];
  const websites = initWebsites({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { total: 2, stopped: 1, not_running: 1, failed: 0 };
    }
  });

  const result = await websites.bulkStop({ website_ids: ["website-1", "website-2"] });

  assert.equal(result.stopped, 1);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/websites/bulk/stop/",
      request: {
        method: "post",
        requestBody: {
          "application/json": { website_ids: ["website-1", "website-2"] }
        }
      }
    }
  ]);
});

test("bulk delete sends website IDs to the bounded delete endpoint", async () => {
  const calls = [];
  const websites = initWebsites({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { total: 2, deleted: 2, not_found: 0, failed: 0 };
    }
  });

  const result = await websites.bulkDelete({ website_ids: ["website-1", "website-2"] });

  assert.equal(result.deleted, 2);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/websites/bulk/delete/",
      request: {
        method: "post",
        requestBody: {
          "application/json": { website_ids: ["website-1", "website-2"] }
        }
      }
    }
  ]);
});
