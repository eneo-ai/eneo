import assert from "node:assert/strict";
import test from "node:test";

import { createEneo } from "../eneo.js";
import { initFederation } from "./federation.js";

test("createEneo exposes the organisation's sign-in settings", () => {
  const eneo = createEneo({ baseUrl: "https://example.test" });

  assert.equal(typeof eneo.federation.get, "function");
  assert.equal(typeof eneo.federation.update, "function");
});

test("sign-in settings are read and changed for the caller's organisation only", async () => {
  const calls = [];
  const federation = initFederation({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return {};
    }
  });
  const patch = { revision: "rev-1", client_id: "new-client" };

  await federation.get();
  await federation.update(patch);

  assert.deepEqual(calls, [
    { endpoint: "/api/v1/admin/federation", request: { method: "get" } },
    {
      endpoint: "/api/v1/admin/federation",
      request: { method: "patch", requestBody: { "application/json": patch } }
    }
  ]);
});
