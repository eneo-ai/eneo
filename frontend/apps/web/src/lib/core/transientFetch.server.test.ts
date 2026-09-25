import { describe, expect, it, vi } from "vitest";
import { fetchWithTransientRetry, isTransientNetworkError } from "./transientFetch.server";

function socketDeath(): TypeError {
  // Shape undici produces when a pooled keep-alive socket dies mid-request.
  return new TypeError("fetch failed", {
    cause: Object.assign(new Error("other side closed"), { code: "UND_ERR_SOCKET" })
  });
}

describe("isTransientNetworkError", () => {
  it("recognises a dead pooled socket through the cause chain", () => {
    expect(isTransientNetworkError(socketDeath())).toBe(true);
    expect(
      isTransientNetworkError(
        new TypeError("fetch failed", {
          cause: Object.assign(new Error("reset"), { code: "ECONNRESET" })
        })
      )
    ).toBe(true);
  });

  it("does not treat refused connections or plain errors as transient", () => {
    // ECONNREFUSED means the backend is down — retrying immediately cannot
    // help and would double the latency of an honest failure.
    expect(
      isTransientNetworkError(
        new TypeError("fetch failed", {
          cause: Object.assign(new Error("refused"), { code: "ECONNREFUSED" })
        })
      )
    ).toBe(false);
    expect(isTransientNetworkError(new Error("boom"))).toBe(false);
    expect(isTransientNetworkError(undefined)).toBe(false);
  });
});

describe("fetchWithTransientRetry", () => {
  it("retries a GET exactly once when the socket dies, on a fresh request", async () => {
    const ok = new Response("ok");
    const fetchFn = vi.fn().mockRejectedValueOnce(socketDeath()).mockResolvedValueOnce(ok);

    const response = await fetchWithTransientRetry(
      new Request("http://backend/api/v1/users/me"),
      fetchFn as unknown as typeof fetch
    );

    expect(response).toBe(ok);
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  it("gives up after the second failure", async () => {
    const fetchFn = vi.fn().mockRejectedValue(socketDeath());

    await expect(
      fetchWithTransientRetry(
        new Request("http://backend/api/v1/users/me"),
        fetchFn as unknown as typeof fetch
      )
    ).rejects.toThrow("fetch failed");
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  it("never retries a non-idempotent method", async () => {
    const fetchFn = vi.fn().mockRejectedValue(socketDeath());

    await expect(
      fetchWithTransientRetry(
        new Request("http://backend/api/v1/conversations/", { method: "POST" }),
        fetchFn as unknown as typeof fetch
      )
    ).rejects.toThrow("fetch failed");
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it("never retries an HTTP error response", async () => {
    const teapot = new Response("no", { status: 418 });
    const fetchFn = vi.fn().mockResolvedValue(teapot);

    const response = await fetchWithTransientRetry(
      new Request("http://backend/api/v1/users/me"),
      fetchFn as unknown as typeof fetch
    );

    expect(response).toBe(teapot);
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it("rethrows non-transient failures without retrying", async () => {
    const fetchFn = vi.fn().mockRejectedValue(new Error("certificate error"));

    await expect(
      fetchWithTransientRetry(
        new Request("http://backend/api/v1/users/me"),
        fetchFn as unknown as typeof fetch
      )
    ).rejects.toThrow("certificate error");
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });
});
