import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createClient } from "../client/client.js";

function recordingFetch() {
  const calls = [];
  return {
    calls,
    fetch: async (input, init) => {
      calls.push({ input, init });
      return new Response(null, { status: 204 });
    }
  };
}

describe("createClient authentication headers", () => {
  it("uses the backend default X-API-Key header", async () => {
    const recorder = recordingFetch();
    const client = createClient({
      baseUrl: "https://eneo.example",
      apiKey: "sk_secret",
      fetch: recorder.fetch
    });

    await client.fetch("/api/v1/version", { method: "get" });

    assert.equal(recorder.calls.length, 1);
    assert.deepEqual(recorder.calls[0].init.headers, { "X-API-Key": "sk_secret" });
  });

  it("supports an installation-specific header name", async () => {
    const recorder = recordingFetch();
    const client = createClient({
      baseUrl: "https://eneo.example",
      apiKey: "sk_secret",
      apiKeyHeaderName: "X-Eneo-Key",
      fetch: recorder.fetch
    });

    await client.fetch("/api/v1/version", { method: "get" });

    assert.deepEqual(recorder.calls[0].init.headers, { "X-Eneo-Key": "sk_secret" });
  });

  it("uses bearer authentication when only a user token is supplied", async () => {
    const recorder = recordingFetch();
    const client = createClient({
      baseUrl: "https://eneo.example",
      token: "user-token",
      fetch: recorder.fetch
    });

    await client.fetch("/api/v1/version", { method: "get" });

    assert.deepEqual(recorder.calls[0].init.headers, {
      Authorization: "Bearer user-token"
    });
  });

  it("sends both module service and user credentials when supplied", async () => {
    const recorder = recordingFetch();
    const client = createClient({
      baseUrl: "https://eneo.example",
      apiKey: "sk_module",
      apiKeyHeaderName: "X-Eneo-Key",
      token: "module-user-token",
      fetch: recorder.fetch
    });

    await client.fetch("/api/v1/version", { method: "get" });

    assert.deepEqual(recorder.calls[0].init.headers, {
      "X-Eneo-Key": "sk_module",
      Authorization: "Bearer module-user-token"
    });
  });
});
