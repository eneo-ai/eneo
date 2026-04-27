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
});
