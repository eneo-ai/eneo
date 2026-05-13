import { describe, expect, it, vi } from "vitest";

import { IntricError, createClient } from "./client";

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
    ).rejects.toBeInstanceOf(IntricError);

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
