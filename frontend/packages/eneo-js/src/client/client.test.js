import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createClient } from "./client.js";

/** A backend that records the address it was asked for and answers `{}`. */
function recordingClient() {
  /** @type {string[]} */
  const requested = [];
  const client = createClient({
    baseUrl: "https://eneo.example.se",
    fetch: async (input) => {
      requested.push(String(input));
      return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    }
  });
  return { client, requested };
}

describe("path parameters", () => {
  it("keeps a value with a slash and dot segments inside its own path segment", async () => {
    const { client, requested } = recordingClient();
    await client.fetch("/api/v1/widgets/{public_id}/config/", {
      method: "get",
      params: { path: { public_id: "wgt_x/../../foo" } }
    });
    // Unencoded, `url.pathname = …` would normalise the dots away and the
    // request would reach /api/v1/foo/config/ instead.
    assert.deepStrictEqual(requested, [
      "https://eneo.example.se/api/v1/widgets/wgt_x%2F..%2F..%2Ffoo/config/"
    ]);
  });

  it("leaves an ordinary identifier as it is", async () => {
    const { client, requested } = recordingClient();
    await client.fetch("/api/v1/widgets/{public_id}/config/", {
      method: "get",
      params: { path: { public_id: "wgt_0123456789abcdefABCDEF" } }
    });
    assert.deepStrictEqual(requested, [
      "https://eneo.example.se/api/v1/widgets/wgt_0123456789abcdefABCDEF/config/"
    ]);
  });
});
