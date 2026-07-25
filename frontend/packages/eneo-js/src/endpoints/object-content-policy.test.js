import assert from "node:assert/strict";
import test from "node:test";

import { createEneo } from "../eneo.js";
import { initObjectContentPolicy } from "./object-content-policy.js";

test("createEneo exposes the object content policy resource", () => {
  const eneo = createEneo({ baseUrl: "https://example.test" });

  assert.equal(typeof eneo.objectContentPolicy.get, "function");
  assert.equal(typeof eneo.objectContentPolicy.replace, "function");
});

test("object content policy uses the deployment-wide GET and replacement PUT contract", async () => {
  const calls = [];
  const objectContentPolicy = initObjectContentPolicy({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { policy: { revision: 4 }, limits: [], capabilities: [], inventory: [] };
    }
  });
  const replacement = {
    expected_revision: 4,
    new_write_storage_target: "object_store",
    session_file_limit_bytes: 20_000_000,
    session_image_limit_bytes: 10_000_000,
    knowledge_file_limit_bytes: 50_000_000,
    transcription_audio_limit_bytes: 100_000_000
  };

  await objectContentPolicy.get();
  await objectContentPolicy.replace(replacement);

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/object-content-policy",
      request: { method: "get" }
    },
    {
      endpoint: "/api/v1/admin/object-content-policy",
      request: {
        method: "put",
        requestBody: { "application/json": replacement }
      }
    }
  ]);
});
