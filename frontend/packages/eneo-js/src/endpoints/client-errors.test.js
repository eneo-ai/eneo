import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createClient, EneoError } from "../client/client.js";

describe("client error privacy", () => {
  const password = "secret password for test";
  const endpoint = "/api/v1/admin/users/test-user/";

  for (const failure of ["connection", "response"]) {
    it(`excludes a submitted password from ${failure} errors`, async () => {
      const client = createClient({
        baseUrl: "https://eneo.example",
        fetch: async (_input, init) => {
          assert.deepEqual(JSON.parse(init.body), { password });
          if (failure === "connection") throw new TypeError("Failed to fetch");
          return Response.json(
            { message: "Password rejected", eneo_error_code: 0 },
            { status: 400, headers: { "X-Trace-Id": "test-trace-id" } }
          );
        }
      });

      await assert.rejects(
        client.fetch(endpoint, {
          method: "post",
          requestBody: { "application/json": { password } }
        }),
        (error) => {
          assert.ok(error instanceof EneoError);
          assert.deepEqual(error.request, { endpoint: `POST@https://eneo.example${endpoint}` });
          assert.equal(JSON.stringify(error).includes(password), false);
          assert.equal(error.status, failure === "connection" ? 0 : 400);
          assert.equal(error.stage, failure === "connection" ? "CONNECTION" : "RESPONSE");
          assert.equal(
            error.getReadableMessage(),
            failure === "connection" ? "Failed to fetch" : "Password rejected"
          );
          assert.equal(error.getTraceId(), failure === "connection" ? undefined : "test-trace-id");
          return true;
        }
      );
    });
  }

  it("excludes submitted content from streaming errors", async () => {
    const client = createClient({
      baseUrl: "https://eneo.example",
      fetch: async () => {
        throw new TypeError("Failed to fetch");
      }
    });

    await assert.rejects(
      client.stream(endpoint, { requestBody: { "application/json": { text: password } } }, {}),
      (error) => {
        assert.ok(error instanceof EneoError);
        assert.deepEqual(error.request, { endpoint: `STREAM@https://eneo.example${endpoint}` });
        assert.equal(JSON.stringify(error).includes(password), false);
        return true;
      }
    );
  });

  it("retains only endpoint metadata when callers supply additional request fields", () => {
    const request = { endpoint, payload: { password } };
    const error = new EneoError("Failed", "CONNECTION", 0, 0, undefined, request);

    assert.deepEqual(error.request, { endpoint });
    assert.equal(JSON.stringify(error).includes(password), false);
  });
});

describe("permission denial body", () => {
  it("reads the message and the numeric category from the error envelope", async () => {
    // The shared role-permission guard used to answer `{"detail": "..."}`, which
    // left the client without a code and the web app without a localizable
    // category. It now answers the envelope every other 403 uses.
    const client = createClient({
      baseUrl: "https://eneo.example",
      fetch: async () =>
        Response.json(
          {
            code: "insufficient_permission",
            message: "Need permission api_keys in order to access",
            eneo_error_code: 9001
          },
          { status: 403 }
        )
    });

    await assert.rejects(
      client.fetch("/api/v1/api-keys", { method: "post", requestBody: { "application/json": {} } }),
      (error) => {
        assert.ok(error instanceof EneoError);
        assert.equal(error.status, 403);
        assert.equal(error.code, 9001);
        assert.equal(error.getReadableMessage(), "Need permission api_keys in order to access");
        return true;
      }
    );
  });
});
