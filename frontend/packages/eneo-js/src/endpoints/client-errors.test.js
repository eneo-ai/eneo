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

  it("does not show a gateway's HTML page as the message of a failed stream", async () => {
    const client = createClient({
      baseUrl: "https://eneo.example",
      fetch: async () =>
        new Response("<html><body>504 Gateway Time-out</body></html>", {
          status: 504,
          headers: { "Content-Type": "text/html" }
        })
    });

    await assert.rejects(
      client.stream(endpoint, { requestBody: { "application/json": {} } }, {}),
      (error) => {
        assert.ok(error instanceof EneoError);
        assert.equal(error.status, 504);
        assert.equal(error.getReadableMessage(), "");
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

describe("client-wide error notification", () => {
  const body = { message: "Choose a new password", eneo_error_code: 9070 };
  const endpoint = "/api/v1/users/tenant/";

  /** Records reported errors; node:test's `mock` is missing under bun test. */
  function recordErrors() {
    const reported = [];
    return { reported, onError: (error) => reported.push(error) };
  }

  for (const transport of ["fetch", "stream", "download", "xhr"]) {
    it(`reports ${transport} refusals and preserves the error for the caller`, async (t) => {
      const { reported, onError } = recordErrors();
      if (transport === "xhr") {
        const original = Object.getOwnPropertyDescriptor(globalThis, "XMLHttpRequest");
        t.after(() => {
          if (original) Object.defineProperty(globalThis, "XMLHttpRequest", original);
          else delete globalThis.XMLHttpRequest;
        });
        globalThis.XMLHttpRequest = class {
          upload = {};
          DONE = 4;
          readyState = 4;
          status = 403;
          statusText = "Forbidden";
          responseText = JSON.stringify(body);
          open() {}
          setRequestHeader() {}
          getAllResponseHeaders() {
            return "content-type: application/json";
          }
          send() {
            this.onload();
          }
        };
      }
      const client = createClient({
        baseUrl: "https://eneo.example",
        fetch: async () => Response.json(body, { status: 403 }),
        onError
      });
      await assert.rejects(client[transport](endpoint, { method: "get" }, {}), (error) => {
        assert.ok(error instanceof EneoError);
        assert.equal(error.status, 403);
        assert.equal(error.code, 9070);
        assert.equal(reported.length, 1);
        assert.equal(reported[0], error);
        return true;
      });
    });
  }

  it("leaves successful API-key requests untouched", async () => {
    const { reported, onError } = recordErrors();
    const client = createClient({
      baseUrl: "https://eneo.example",
      apiKey: "sk_test",
      fetch: async (_url, init) => {
        assert.equal(init.headers["X-API-Key"], "sk_test");
        return Response.json({ name: "Tenant" });
      },
      onError
    });
    assert.deepEqual(await client.fetch(endpoint, { method: "get" }), { name: "Tenant" });
    assert.equal(reported.length, 0);
  });
});
