import assert from "node:assert/strict";
import test from "node:test";

import { initTranscriptionServices } from "./transcription-services.js";

/** A client that records each request and answers with one page. */
function recordingClient() {
  const calls = [];
  return {
    calls,
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, query: request.params.query });
      return { items: [{ id: "a" }], has_more: false };
    }
  };
}

for (const [method, endpoint] of [
  ["list", "/api/v1/admin/transcription-services/"],
  ["listCatalogue", "/api/v1/transcription-services/"]
]) {
  test(`${method} asks for the page it is given`, async () => {
    const client = recordingClient();

    const page = await initTranscriptionServices(client)[method]({ limit: 200, offset: 0 });

    assert.deepEqual(page.items, [{ id: "a" }]);
    assert.deepEqual(client.calls, [{ endpoint, query: { limit: 200, offset: 0 } }]);
  });
}
