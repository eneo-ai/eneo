import assert from "node:assert/strict";
import test from "node:test";

import { initWhatsNew } from "./whats-new.js";

test("what's new markers use the session-only routes", async () => {
  const calls = [];
  const whatsNew = initWhatsNew({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { seen_version: "2.2.0", announced_version: "2.2.0" };
    }
  });

  assert.deepEqual(await whatsNew.getState(), {
    seen_version: "2.2.0",
    announced_version: "2.2.0"
  });
  await whatsNew.markSeen("2.2.0");
  await whatsNew.markAnnounced("2.2.0");

  assert.deepEqual(calls, [
    { endpoint: "/api/v1/whats-new/state/", request: { method: "get" } },
    {
      endpoint: "/api/v1/whats-new/seen/",
      request: { method: "put", requestBody: { "application/json": { version: "2.2.0" } } }
    },
    {
      endpoint: "/api/v1/whats-new/announced/",
      request: { method: "put", requestBody: { "application/json": { version: "2.2.0" } } }
    }
  ]);
});
