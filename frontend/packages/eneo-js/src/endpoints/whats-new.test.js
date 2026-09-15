import assert from "node:assert/strict";
import test from "node:test";

import { initWhatsNew } from "./whats-new.js";

test("what's new read marker uses the session-only seen route", async () => {
  const calls = [];
  const whatsNew = initWhatsNew({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { version: "2.2.0", seen_at: "2026-09-15T10:00:00Z" };
    }
  });

  assert.deepEqual(await whatsNew.getSeen(), {
    version: "2.2.0",
    seen_at: "2026-09-15T10:00:00Z"
  });
  await whatsNew.markSeen("2.2.0");

  assert.deepEqual(calls, [
    { endpoint: "/api/v1/whats-new/seen/", request: { method: "get" } },
    {
      endpoint: "/api/v1/whats-new/seen/",
      request: {
        method: "put",
        requestBody: { "application/json": { version: "2.2.0" } }
      }
    }
  ]);
});
