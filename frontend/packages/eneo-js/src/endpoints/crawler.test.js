import assert from "node:assert/strict";
import test from "node:test";

import { createEneo } from "../eneo.js";
import { initCrawler } from "./crawler.js";

test("createEneo exposes native crawler diagnostics", () => {
  const eneo = createEneo({ baseUrl: "https://example.test" });

  assert.equal(typeof eneo.crawler.diagnostics, "function");
  assert.equal(typeof eneo.crawler.probe, "function");
});

test("crawler diagnostics and audited probe use tenant-scoped contracts", async () => {
  const calls = [];
  const crawler = initCrawler({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return {};
    }
  });

  await crawler.diagnostics();
  await crawler.probe("website-id");

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/crawler/diagnostics/",
      request: { method: "get" }
    },
    {
      endpoint: "/api/v1/crawler/diagnostics/{website_id}/probe/",
      request: {
        method: "post",
        params: { path: { website_id: "website-id" } }
      }
    }
  ]);
});
