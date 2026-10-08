import { DEFAULT_LANDING_PAGE } from "$lib/core/constants";
import type { Cookies, RequestEvent } from "@sveltejs/kit";
import { describe, expect, test, vi } from "vitest";

const requestEvent = vi.hoisted(() => ({
  cookies: {
    delete: vi.fn(),
    set: vi.fn()
  }
}));

vi.mock("$app/server", () => ({
  getRequestEvent: () => requestEvent
}));

import {
  authenticateUser,
  clearFrontendCookies,
  consumeOidcLoginAttempt,
  encodeState,
  EneoAccessTokenCookie,
  OidcLoginAttemptCookie,
  startOidcLoginAttempt,
  resolveLoginStateDestination,
  resolveSafeLoginDestination,
  setFrontendAuthCookie
} from "./auth.server";

test("setting an Eneo-only session clears a stale provider access token", async () => {
  vi.clearAllMocks();
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 }));

  await setFrontendAuthCookie({ id_token: `header.${payload}.signature` });

  expect(requestEvent.cookies.set).toHaveBeenCalledWith(
    "auth",
    expect.any(String),
    expect.objectContaining({ httpOnly: true, path: "/", sameSite: "lax" })
  );
  expect(requestEvent.cookies.delete).toHaveBeenCalledWith(EneoAccessTokenCookie, { path: "/" });
});

describe("resolveSafeLoginDestination", () => {
  test("preserves a local module handoff path byte-for-byte", () => {
    const destination =
      "/module-login?module_key=tal-till-text&state=a%252Fb%26c%3Dd&redirect_uri=https%3A%2F%2Fmodule.example%2Fcallback";

    expect(resolveSafeLoginDestination(destination)).toBe(destination);
  });

  test.each([
    "https://evil.example/module-login",
    "//evil.example/module-login",
    "/\\evil.example/module-login",
    "/%5Cevil.example/module-login",
    "/module-login?state=bad%",
    "/module-login%0ASet-Cookie:bad=1",
    "module-login"
  ])("rejects unsafe or malformed destination %s", (destination) => {
    expect(resolveSafeLoginDestination(destination)).toBe(DEFAULT_LANDING_PAGE);
  });

  test("falls back for non-string state values", () => {
    expect(resolveSafeLoginDestination(null)).toBe(DEFAULT_LANDING_PAGE);
    expect(resolveSafeLoginDestination({ pathname: "/module-login" })).toBe(DEFAULT_LANDING_PAGE);
  });
});

describe("resolveLoginStateDestination", () => {
  test("reads the local destination from a valid provider state", () => {
    const destination = "/module-login?state=opaque%2526value";
    const state = encodeState({ loginMethod: "oidc", next: destination });

    expect(resolveLoginStateDestination(state)).toBe(destination);
  });

  test("does not turn a manipulated provider state into an external redirect", () => {
    const state = JSON.stringify({ loginMethod: "oidc", next: "//evil.example" });

    expect(resolveLoginStateDestination(state)).toBe(DEFAULT_LANDING_PAGE);
    expect(resolveLoginStateDestination("not-json")).toBe(DEFAULT_LANDING_PAGE);
  });
});

describe("generic OIDC browser login attempt", () => {
  const ATTEMPT_A = "11111111-1111-4111-8111-111111111111";
  const ATTEMPT_B = "22222222-2222-4222-8222-222222222222";

  function callbackState(attemptId: string, destination: string | null): string {
    const frontendState = encodeState({ loginMethod: "oidc", next: destination, attemptId });
    const payload = btoa(JSON.stringify({ frontend_state: frontendState }))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=/g, "");
    return `header.${payload}.signature`;
  }

  function cookieJar(initialValue?: string) {
    let value = initialValue;
    const cookies = {
      get: vi.fn((name: string) => (name === OidcLoginAttemptCookie ? value : undefined)),
      set: vi.fn((name: string, nextValue: string) => {
        if (name === OidcLoginAttemptCookie) value = nextValue;
      }),
      delete: vi.fn((name: string) => {
        if (name === OidcLoginAttemptCookie) value = undefined;
      })
    };
    return cookies;
  }

  test("stores and consumes one exact bound destination with hardened attributes", async () => {
    const destination = "/module-login?state=opaque%2526value";
    const cookies = cookieJar();

    startOidcLoginAttempt(
      cookies as never,
      destination,
      ATTEMPT_A,
      Math.floor(Date.now() / 1000) + 600
    );

    expect(cookies.set).toHaveBeenCalledWith(OidcLoginAttemptCookie, expect.any(String), {
      path: "/",
      httpOnly: true,
      maxAge: 600,
      secure: expect.any(Boolean),
      sameSite: "lax"
    });
    expect(JSON.parse(cookies.get(OidcLoginAttemptCookie) ?? "{}")).toEqual({
      attemptId: ATTEMPT_A,
      destination,
      expiresAt: expect.any(Number)
    });
    await expect(
      consumeOidcLoginAttempt(cookies as never, callbackState(ATTEMPT_A, destination))
    ).resolves.toEqual({ status: "matched", destination });
    expect(cookies.delete).toHaveBeenCalledWith(OidcLoginAttemptCookie, { path: "/" });
    await expect(
      consumeOidcLoginAttempt(cookies as never, callbackState(ATTEMPT_A, destination))
    ).resolves.toEqual({ status: "missing" });
  });

  test("does not consume a parallel login attempt's destination", async () => {
    const destination = "/module-login?state=attempt-a";
    const cookies = cookieJar();
    startOidcLoginAttempt(
      cookies as never,
      destination,
      ATTEMPT_A,
      Math.floor(Date.now() / 1000) + 600
    );

    await expect(
      consumeOidcLoginAttempt(cookies as never, callbackState(ATTEMPT_B, destination))
    ).resolves.toEqual({ status: "mismatch" });
    expect(cookies.delete).not.toHaveBeenCalled();

    await expect(
      consumeOidcLoginAttempt(cookies as never, callbackState(ATTEMPT_A, destination))
    ).resolves.toEqual({ status: "matched", destination });
    expect(cookies.delete).toHaveBeenCalledWith(OidcLoginAttemptCookie, { path: "/" });
  });

  test.each([null, "//evil.example/module-login", `/${"x".repeat(4000)}`])(
    "keeps authentication bound when the optional destination is absent or discarded",
    async (destination) => {
      const cookies = cookieJar();
      startOidcLoginAttempt(
        cookies as never,
        destination,
        ATTEMPT_A,
        Math.floor(Date.now() / 1000) + 600
      );

      await expect(
        consumeOidcLoginAttempt(cookies as never, callbackState(ATTEMPT_A, null))
      ).resolves.toEqual({ status: "matched", destination: null });
    }
  );

  test.each(["null", "not-json", JSON.stringify({ attemptId: ATTEMPT_A, destination: "/" })])(
    "rejects malformed or pre-upgrade attempts without authentication fallback",
    async (value) => {
      const cookies = cookieJar(value);
      await expect(
        consumeOidcLoginAttempt(cookies as never, callbackState(ATTEMPT_A, null))
      ).resolves.toEqual({ status: "invalid" });
      expect(cookies.delete).toHaveBeenCalledWith(OidcLoginAttemptCookie, { path: "/" });
    }
  );

  test("rejects an unsafe destination in a manipulated cookie", async () => {
    const externalCookies = cookieJar(
      JSON.stringify({
        attemptId: ATTEMPT_A,
        destination: "//evil.example/module-login",
        expiresAt: Math.floor(Date.now() / 1000) + 600
      })
    );

    await expect(
      consumeOidcLoginAttempt(externalCookies as never, callbackState(ATTEMPT_A, "/module-login"))
    ).resolves.toEqual({ status: "invalid" });
    expect(externalCookies.delete).toHaveBeenCalledWith(OidcLoginAttemptCookie, { path: "/" });
  });

  test("rejects and clears an expired attempt even if the browser sends it", async () => {
    const cookies = cookieJar(
      JSON.stringify({
        attemptId: ATTEMPT_A,
        destination: null,
        expiresAt: Math.floor(Date.now() / 1000) - 1
      })
    );
    await expect(
      consumeOidcLoginAttempt(cookies as never, callbackState(ATTEMPT_A, null))
    ).resolves.toEqual({ status: "expired" });
    expect(cookies.delete).toHaveBeenCalledWith(OidcLoginAttemptCookie, { path: "/" });
  });
});

/**
 * A stand-in for SvelteKit's cookie jar with the behaviour that matters here:
 * `delete` writes an expiring cookie for a given path, and `get` stops seeing a
 * name once it has been deleted for a path covering the request.
 */
function cookieJar(initial: Record<string, string>) {
  const values = new Map(Object.entries(initial));
  const deleted: Array<{ name: string; path: string }> = [];

  const cookies = {
    getAll: () => Array.from(values, ([name, value]) => ({ name, value })),
    get: (name: string) => values.get(name),
    delete: (name: string, options: { path: string }) => {
      deleted.push({ name, path: options.path });
      if (options.path === "/") values.delete(name);
    }
  } as unknown as Cookies;

  return { cookies, deleted };
}

describe("clearFrontendCookies", () => {
  test("expires every cookie the request carried, at the path they are set on", () => {
    const jar = cookieJar({
      auth: "id-token",
      acc: "access-token",
      mobilityguard: "verifier",
      PARAGLIDE_LOCALE: "sv"
    });

    clearFrontendCookies({ cookies: jar.cookies } as RequestEvent);

    // Every cookie this app sets uses path "/", so one delete per name clears it.
    expect(jar.deleted).toEqual([
      { name: "auth", path: "/" },
      { name: "acc", path: "/" },
      { name: "mobilityguard", path: "/" },
      { name: "PARAGLIDE_LOCALE", path: "/" }
    ]);
  });

  test("leaves the same request unauthenticated, not just the next one", () => {
    // authHandle clears and then reads the tokens in the same pass; if the
    // deletion were only visible on the following request, the user would stay
    // logged in on the page that was meant to reset them.
    const jar = cookieJar({ auth: "id-token", acc: "access-token" });
    const event = { cookies: jar.cookies } as RequestEvent;

    clearFrontendCookies(event);

    expect(authenticateUser(event)).toEqual({ id_token: undefined, access_token: undefined });
  });
});
