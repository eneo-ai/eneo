import { beforeEach, describe, expect, test, vi } from "vitest";

const state = vi.hoisted(() => ({
  env: {} as Record<string, string>,
  cookies: new Map<string, string>(),
  fetch: vi.fn(),
  setFrontendAuthCookie: vi.fn()
}));

vi.mock("$env/dynamic/private", () => ({ env: state.env }));
vi.mock("$lib/core/environment.server", () => ({ getBackendUrl: () => "https://backend.example" }));
vi.mock("$app/server", () => ({
  getRequestEvent: () => ({
    url: new URL("https://eneo.example/login/callback"),
    cookies: {
      get: (name: string) => state.cookies.get(name),
      delete: (name: string) => state.cookies.delete(name)
    },
    fetch: state.fetch
  })
}));
vi.mock("./auth.server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./auth.server")>()),
  setFrontendAuthCookie: state.setFrontendAuthCookie
}));

import type { Cookies } from "@sveltejs/kit";
import {
  clearMobilityguardCookie,
  getMobilityguardLink,
  loginWithMobilityguard
} from "./mobilityguard.server";

const VERIFIER_COOKIE = "mobilityguard-verifier";

function eventCookies() {
  return {
    set: vi.fn((name: string, value: string) => state.cookies.set(name, value)),
    delete: vi.fn((name: string) => state.cookies.delete(name))
  } as unknown as Cookies & { set: ReturnType<typeof vi.fn>; delete: ReturnType<typeof vi.fn> };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(console, "debug").mockImplementation(() => undefined);
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  state.cookies.clear();
  Object.assign(state.env, {
    MOBILITYGUARD_CLIENT_ID: "mg-client",
    MOBILITY_GUARD_AUTH: "https://mg.example/authorize",
    PUBLIC_ORIGIN: "https://eneo.example/"
  });
});

describe("the MobilityGuard authorization link", () => {
  test("asks for openid and email with PKCE S256 and stores the verifier", async () => {
    const cookies = eventCookies();
    const link = await getMobilityguardLink({
      url: new URL("https://eneo.example/login?next=/spaces"),
      cookies
    });

    const url = new URL(link!);
    expect(`${url.origin}${url.pathname}`).toBe("https://mg.example/authorize");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      scope: "openid email",
      client_id: "mg-client",
      response_type: "code",
      redirect_uri: "https://eneo.example/login/callback",
      state: JSON.stringify({ loginMethod: "mobilityguard", next: "/spaces" }),
      code_challenge: expect.stringMatching(/^[A-Za-z0-9_-]{43}$/),
      code_challenge_method: "S256"
    });
    expect(cookies.set).toHaveBeenCalledWith(
      VERIFIER_COOKIE,
      expect.any(String),
      expect.objectContaining({ path: "/", httpOnly: true, sameSite: "lax" })
    );
  });

  test("is not offered without its configuration", async () => {
    delete state.env.MOBILITY_GUARD_AUTH;
    vi.spyOn(console, "warn").mockImplementation(() => undefined);

    expect(
      await getMobilityguardLink({
        url: new URL("https://eneo.example/login"),
        cookies: eventCookies()
      })
    ).toBeUndefined();
  });
});

describe("the MobilityGuard code exchange", () => {
  test("posts the code and verifier to the backend route and keeps its token", async () => {
    state.cookies.set(VERIFIER_COOKIE, "stored-verifier");
    state.fetch.mockResolvedValue(
      new Response(JSON.stringify({ access_token: "eneo-token", token_type: "bearer" }), {
        status: 200
      })
    );

    expect(await loginWithMobilityguard("the-code")).toBe(true);

    expect(state.fetch).toHaveBeenCalledOnce();
    const [url, request] = state.fetch.mock.calls[0];
    expect(url).toBe("https://backend.example/api/v1/users/login/openid-connect/mobilityguard/");
    expect(request.method).toBe("POST");
    expect(JSON.parse(request.body)).toEqual({
      code: "the-code",
      code_verifier: "stored-verifier",
      scope: "openid+email",
      redirect_uri: "https://eneo.example/login/callback",
      client_id: "mg-client"
    });
    expect(state.setFrontendAuthCookie).toHaveBeenCalledWith({ id_token: "eneo-token" });
    expect(state.cookies.has(VERIFIER_COOKIE)).toBe(false);
  });

  test.each([401, 403, 500, 502])("a %i from the backend signs nobody in", async (status) => {
    state.cookies.set(VERIFIER_COOKIE, "stored-verifier");
    state.fetch.mockResolvedValue(new Response(JSON.stringify({ detail: "refused" }), { status }));

    expect(await loginWithMobilityguard("the-code")).toBe(false);

    expect(state.setFrontendAuthCookie).not.toHaveBeenCalled();
  });

  test("without the verifier cookie nothing is sent", async () => {
    expect(await loginWithMobilityguard("the-code")).toBe(false);

    expect(state.fetch).not.toHaveBeenCalled();
  });

  test("clearing removes the verifier cookie", () => {
    const cookies = eventCookies();

    clearMobilityguardCookie(cookies);

    expect(cookies.delete).toHaveBeenCalledWith(VERIFIER_COOKIE, { path: "/" });
  });
});
