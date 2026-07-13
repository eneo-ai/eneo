import { describe, expect, it, vi } from "vitest";

import { EneoError, createClient } from "./client";

describe("createClient path parameters", () => {
  it("does not send requests with missing path parameters", async () => {
    const fetch = vi.fn();
    const client = createClient({ baseUrl: "https://api.example.test", fetch });

    await expect(
      client.fetch("/api/v1/apps/{id}/", {
        method: "get",
        params: { path: { id: undefined } }
      })
    ).rejects.toMatchObject({
      message: 'Cannot build API request: path parameter "id" is missing.',
      stage: "CONNECTION",
      status: 0
    });

    expect(fetch).not.toHaveBeenCalled();
  });

  it("treats string undefined as a missing path parameter", async () => {
    const fetch = vi.fn();
    const client = createClient({ baseUrl: "https://api.example.test", fetch });

    await expect(
      client.fetch("/api/v1/app-runs/{id}/", {
        method: "get",
        params: { path: { id: "undefined" } }
      })
    ).rejects.toBeInstanceOf(EneoError);

    expect(fetch).not.toHaveBeenCalled();
  });

  it("sends valid path parameters unchanged", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ id: "app-1" }), { status: 200 }));
    const client = createClient({ baseUrl: "https://api.example.test", fetch });

    await client.fetch("/api/v1/apps/{id}/", {
      method: "get",
      params: { path: { id: "app-1" } }
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("https://api.example.test/api/v1/apps/app-1/");
  });

  it("authenticates apiKey clients with the canonical X-API-Key header", async () => {
    const fetch = vi.fn(
      async () => new Response(JSON.stringify({ statuses: [] }), { status: 200 })
    );
    const apiKey = "synthetic-auth-value";
    const client = createClient({ baseUrl: "https://api.example.test", apiKey, fetch });

    await client.fetch("/api/v1/flows/runs/status-capabilities/", { method: "get" });

    expect(fetch).toHaveBeenCalledTimes(1);
    const requestHeaders = new Headers(fetch.mock.calls[0][1].headers);
    expect(requestHeaders.get("X-API-Key")).toBe(apiKey);
    expect(requestHeaders.has("api-key")).toBe(false);
  });

  it("forwards typed header parameters and caller headers", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ id: "run-1" }), { status: 200 }));
    const client = createClient({ baseUrl: "https://api.example.test", fetch });

    await client.fetch("/api/v1/flows/{id}/runs/", {
      method: "post",
      params: {
        path: { id: "flow-1" },
        header: { "Idempotency-Key": "flow-run:test-key" }
      },
      headers: { "X-Request-Source": "frontend-test" },
      requestBody: { "application/json": {} }
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1].headers).toMatchObject({
      "Content-Type": "application/json",
      "Idempotency-Key": "flow-run:test-key",
      "X-Request-Source": "frontend-test"
    });
  });

  it("exposes backend trace headers on client errors", () => {
    const error = new EneoError(
      "Backend failed",
      "RESPONSE",
      500,
      0,
      {},
      { endpoint: "GET@https://api.example.test/api/v1/info/" },
      new Headers({ "X-Trace-Id": "trace-1" })
    );

    expect(error.getTraceId()).toBe("trace-1");
  });

  it("fails xhr requests before opening a pre-aborted upload", async () => {
    const client = createClient({ baseUrl: "https://api.example.test", fetch: vi.fn() });
    const abortController = new AbortController();
    abortController.abort();

    await expect(
      client.xhr(
        "/api/v1/files/",
        {
          method: "post",
          requestBody: { "multipart/form-data": new FormData() }
        },
        {},
        abortController
      )
    ).rejects.toMatchObject({
      message: "Cancelled after receiving abort signal.",
      stage: "CONNECTION",
      status: 0
    });
  });
});

describe("createClient query parameters", () => {
  it("keeps scalar query behavior and repeats array values in caller order", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ items: [] }), { status: 200 }));
    const client = createClient({ baseUrl: "https://api.example.test", fetch });
    /** @type {NonNullable<NonNullable<import("../types/schema").operations["list_flow_runs"]["parameters"]["query"]>["status"]>} */
    const statuses = ["completed", "queued", "completed"];
    const originalStatuses = [...statuses];

    await client.fetch("/api/v1/flows/{id}/runs/", {
      method: "get",
      params: {
        path: { id: "flow-1" },
        query: { limit: 25, offset: 0, status: statuses }
      }
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe(
      "https://api.example.test/api/v1/flows/flow-1/runs/?limit=25&offset=0&status=completed&status=queued&status=completed"
    );
    expect(statuses).toEqual(originalStatuses);
  });

  it("preserves scalar null, omits undefined, and emits nothing for an empty array", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ items: [] }), { status: 200 }));
    const client = createClient({ baseUrl: "https://api.example.test", fetch });

    await client.fetch("/api/v1/flows/{id}/runs/", {
      method: "get",
      params: {
        path: { id: "flow-1" },
        query: { limit: 0, offset: undefined, status: null }
      }
    });
    await client.fetch("/api/v1/flows/{id}/runs/", {
      method: "get",
      params: {
        path: { id: "flow-1" },
        query: { status: [] }
      }
    });

    expect(fetch.mock.calls.map((call) => call[0])).toEqual([
      "https://api.example.test/api/v1/flows/flow-1/runs/?limit=0&status=null",
      "https://api.example.test/api/v1/flows/flow-1/runs/"
    ]);
  });
});

describe("EneoError readable messages", () => {
  it("reads validation messages from GeneralError details without changing error code fields", async () => {
    const client = createClient({
      baseUrl: "https://api.example.test",
      fetch: vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              message: "Request validation failed.",
              eneo_error_code: 4220,
              code: "request_validation_error",
              request_id: "request-1",
              details: {
                errors: [
                  {
                    location: ["body", "name"],
                    message: "Name is required.",
                    type: "missing"
                  }
                ]
              }
            }),
            { status: 422 }
          )
      )
    });

    let caught;
    try {
      await client.fetch("/api/v1/flows/", {
        method: "post",
        requestBody: { "application/json": {} }
      });
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(EneoError);
    expect(caught.getReadableMessage()).toBe("Name is required.");
    expect(caught.code).toBe(4220);
    expect(caught.response.code).toBe("request_validation_error");
  });

  it("falls back to the GeneralError message when validation details are absent", () => {
    const error = new EneoError(
      "Request validation failed.",
      "RESPONSE",
      422,
      4220,
      {
        message: "Request validation failed.",
        eneo_error_code: 4220,
        code: "request_validation_error"
      },
      { endpoint: "POST@test" }
    );

    expect(error.getReadableMessage()).toBe("Request validation failed.");
  });

  it("keeps legacy FastAPI validation messages working", () => {
    const reasonError = new EneoError(
      "See details for more info.",
      "RESPONSE",
      422,
      0,
      { detail: [{ ctx: { reason: "Legacy reason." }, msg: "Legacy message." }] },
      { endpoint: "POST@test" }
    );
    const msgError = new EneoError(
      "See details for more info.",
      "RESPONSE",
      422,
      0,
      { detail: [{ msg: "Legacy message." }] },
      { endpoint: "POST@test" }
    );

    expect(reasonError.getReadableMessage()).toBe("Legacy reason.");
    expect(msgError.getReadableMessage()).toBe("Legacy message.");
  });

  it.each([
    ["string detail", { detail: "Invalid request body." }, "See details for more info."],
    ["malformed detail", { detail: { unexpected: true } }, "See details for more info."],
    ["no response body", undefined, "Request validation failed."]
  ])("does not throw for %s validation responses", (_case, response, message) => {
    const error = new EneoError(message, "RESPONSE", 422, 0, response, { endpoint: "POST@test" });

    expect(() => error.getReadableMessage()).not.toThrow();
    expect(error.getReadableMessage()).toBe(message);
  });
});
