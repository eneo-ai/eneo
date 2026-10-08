import type { RequestEvent } from "@sveltejs/kit";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const state = vi.hoisted(() => ({
  privateEnv: {} as Record<string, string | undefined>,
  publicEnv: {} as Record<string, string | undefined>
}));

vi.mock("$env/dynamic/private", () => ({ env: state.privateEnv }));
vi.mock("$env/dynamic/public", () => ({ env: state.publicEnv }));

const { handleFetch, resolveBackendServerUrl } = await import("./hooks.server");

describe("resolveBackendServerUrl", () => {
  test("rewrites a backend request to the internal server URL", () => {
    expect(
      resolveBackendServerUrl(
        "https://eneo.example.com/api/v1/spaces/?page=2",
        "https://eneo.example.com",
        "http://backend:8000"
      )
    ).toBe("http://backend:8000/api/v1/spaces/?page=2");
  });

  test("matches the backend origin after URL normalisation", () => {
    for (const backendUrl of [
      "https://Eneo.Example.com",
      "https://eneo.example.com:443",
      "https://eneo.example.com/"
    ]) {
      expect(
        resolveBackendServerUrl(
          "https://eneo.example.com/api/v1/users/login/token/",
          backendUrl,
          "http://backend:8000/"
        )
      ).toBe("http://backend:8000/api/v1/users/login/token/");
    }
  });

  test("calls the public URL as is when no server URL is configured", () => {
    for (const serverUrl of [undefined, "", "not a url"]) {
      expect(
        resolveBackendServerUrl(
          "https://eneo.example.com/api/v1/spaces/",
          "https://eneo.example.com",
          serverUrl
        )
      ).toBe("https://eneo.example.com/api/v1/spaces/");
    }
  });

  test("honours a path prefix on the backend URL", () => {
    expect(
      resolveBackendServerUrl(
        "https://eneo.example.com/eneo/api/v1/spaces/",
        "https://eneo.example.com/eneo/",
        "http://backend:8000"
      )
    ).toBe("http://backend:8000/api/v1/spaces/");
    expect(
      resolveBackendServerUrl(
        "https://eneo.example.com/other/api/v1/spaces/",
        "https://eneo.example.com/eneo",
        "http://backend:8000"
      )
    ).toBeNull();
  });

  test("leaves requests to other hosts alone", () => {
    expect(
      resolveBackendServerUrl(
        "https://idp.example.com/token",
        "https://eneo.example.com",
        "http://backend:8000"
      )
    ).toBeNull();
    expect(
      resolveBackendServerUrl("https://eneo.example.com/api", undefined, undefined)
    ).toBeNull();
    expect(
      resolveBackendServerUrl("https://eneo.example.com/api", "nonsense", undefined)
    ).toBeNull();
  });
});

describe("handleFetch", () => {
  const event = {} as RequestEvent;
  const kitFetch = vi.fn<typeof fetch>();
  const globalFetch = vi.fn<typeof fetch>();

  beforeEach(() => {
    state.privateEnv.ENEO_BACKEND_URL = "https://eneo.example.com";
    state.privateEnv.ENEO_BACKEND_SERVER_URL = "http://backend:8000";
    kitFetch.mockReset().mockResolvedValue(new Response("from sveltekit"));
    globalFetch.mockReset().mockResolvedValue(new Response("from backend"));
    vi.stubGlobal("fetch", globalFetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function sentRequest(): Request {
    const [request] = globalFetch.mock.calls[0];
    if (!(request instanceof Request)) throw new Error("expected a Request");
    return request;
  }

  test("sends backend calls to the internal URL without a browser Origin", async () => {
    const request = new Request("https://eneo.example.com/api/v1/users/login/token/", {
      method: "POST",
      body: new URLSearchParams({ username: "user", password: "secret" }),
      headers: { "Content-Type": "application/x-www-form-urlencoded" }
    });

    const response = await handleFetch({ event, request, fetch: kitFetch });

    expect(await response.text()).toBe("from backend");
    expect(kitFetch).not.toHaveBeenCalled();
    const sent = sentRequest();
    expect(sent.url).toBe("http://backend:8000/api/v1/users/login/token/");
    expect(sent.method).toBe("POST");
    expect(sent.headers.has("origin")).toBe(false);
    expect(sent.headers.get("content-type")).toBe("application/x-www-form-urlencoded");
    expect(await sent.text()).toBe("username=user&password=secret");
  });

  test("calls the public backend URL itself when no server URL is set", async () => {
    state.privateEnv.ENEO_BACKEND_SERVER_URL = "";
    const request = new Request("https://eneo.example.com/api/v1/spaces/");

    await handleFetch({ event, request, fetch: kitFetch });

    expect(kitFetch).not.toHaveBeenCalled();
    expect(sentRequest().url).toBe("https://eneo.example.com/api/v1/spaces/");
  });

  test("hands requests to other hosts to SvelteKit's fetch", async () => {
    const request = new Request("https://idp.example.com/token", { method: "POST", body: "x" });

    const response = await handleFetch({ event, request, fetch: kitFetch });

    expect(await response.text()).toBe("from sveltekit");
    expect(globalFetch).not.toHaveBeenCalled();
    expect(kitFetch.mock.calls[0][0]).toBe(request);
  });
});
