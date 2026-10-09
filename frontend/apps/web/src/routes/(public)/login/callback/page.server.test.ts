import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  clearMobilityguardCookie: vi.fn(),
  clearZitadelCookie: vi.fn(),
  loginWithMobilityguard: vi.fn(),
  loginWithOidc: vi.fn(),
  loginWithZitadel: vi.fn()
}));

vi.mock("$lib/features/auth/mobilityguard.server", () => ({
  clearMobilityguardCookie: mocks.clearMobilityguardCookie,
  loginWithMobilityguard: mocks.loginWithMobilityguard
}));
vi.mock("$lib/features/auth/oidc.server", () => ({
  loginWithOidc: mocks.loginWithOidc
}));
vi.mock("$lib/features/auth/zitadel.server", () => ({
  clearZitadelCookie: mocks.clearZitadelCookie,
  loginWithZitadel: mocks.loginWithZitadel
}));

import { load as authCallbackLoad } from "../../auth/callback/+page.server";
import { load as loginCallbackLoad } from "./+page.server";
import { DEFAULT_LANDING_PAGE } from "$lib/core/constants";

const RESUME_COOKIE = "oidc-login-resume";
const ATTEMPT_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ATTEMPT_ID = "22222222-2222-4222-8222-222222222222";

function frontendState(destination: string | null, attemptId = ATTEMPT_ID): string {
  return JSON.stringify({ loginMethod: "oidc", next: destination, attemptId });
}

function callbackState(state: string): string {
  const payload = btoa(JSON.stringify({ frontend_state: state }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
  return `header.${payload}.signature`;
}

function cookieJar(
  destination?: string | null,
  attemptId = ATTEMPT_ID,
  expiresAt = Math.floor(Date.now() / 1000) + 600
) {
  const values = new Map<string, string>([["auth", "existing-session"]]);
  if (destination !== undefined) {
    values.set(RESUME_COOKIE, JSON.stringify({ attemptId, destination, expiresAt }));
  }
  return {
    get: vi.fn((name: string) => values.get(name)),
    set: vi.fn((name: string, value: string) => values.set(name, value)),
    delete: vi.fn((name: string) => {
      values.delete(name);
    })
  };
}

function callbackEvent(path: string, cookies = cookieJar()) {
  return {
    url: new URL(`https://eneo.example${path}`),
    cookies,
    fetch: vi.fn()
  };
}

describe("generic OIDC browser-bound callback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test.each([
    ["/login/callback", "/login/callback", loginCallbackLoad],
    ["/auth/callback alias", "/auth/callback", authCallbackLoad]
  ])("%s redirects to the exact backend-validated frontend destination", async (_, path, load) => {
    const destination =
      "/module-login?module_key=tal-till-text&state=a%252Fb%26c%3Dd&redirect_uri=https%3A%2F%2Fmodule.example%2Fcallback";
    const state = frontendState(destination);
    const signedState = callbackState(state);
    const cookies = cookieJar(destination);
    mocks.loginWithOidc.mockResolvedValue({
      frontendState: state
    });

    await expect(
      load(callbackEvent(`${path}?code=authorization-code&state=${signedState}`, cookies) as never)
    ).rejects.toMatchObject({ status: 302, location: destination });

    expect(mocks.loginWithOidc).toHaveBeenCalledWith(
      "authorization-code",
      signedState,
      expect.any(Function)
    );
    expect(cookies.delete).toHaveBeenCalledWith(RESUME_COOKIE, { path: "/" });
  });

  test("a bound login without next exchanges the code and uses the default destination", async () => {
    const state = frontendState(null);
    const cookies = cookieJar(null);
    mocks.loginWithOidc.mockResolvedValue({ frontendState: state });

    await expect(
      loginCallbackLoad(
        callbackEvent(
          `/login/callback?code=authorization-code&state=${callbackState(state)}`,
          cookies
        ) as never
      )
    ).rejects.toMatchObject({ status: 302, location: DEFAULT_LANDING_PAGE });

    expect(mocks.loginWithOidc).toHaveBeenCalledOnce();
    expect(cookies.get(RESUME_COOKIE)).toBeUndefined();
  });

  test.each([
    ["missing browser cookie", () => cookieJar()],
    ["another browser attempt", () => cookieJar(null, OTHER_ATTEMPT_ID)],
    ["expired attempt", () => cookieJar(null, ATTEMPT_ID, Math.floor(Date.now() / 1000) - 1)],
    [
      "pre-upgrade cookie",
      () => {
        const cookies = cookieJar();
        cookies.set(RESUME_COOKIE, JSON.stringify({ attemptId: ATTEMPT_ID, destination: "/" }));
        cookies.set.mockClear();
        return cookies;
      }
    ]
  ])(
    "%s rejects a transferred callback before exchange and preserves the session",
    async (_, makeCookies) => {
      const cookies = makeCookies();
      const signedState = callbackState(frontendState(null));

      await expect(
        loginCallbackLoad(
          callbackEvent(`/login/callback?code=attacker-code&state=${signedState}`, cookies) as never
        )
      ).rejects.toMatchObject({ status: 302, location: "/login?message=oidc_attempt_rejected" });

      expect(mocks.loginWithOidc).not.toHaveBeenCalled();
      expect(cookies.set).not.toHaveBeenCalled();
      expect(cookies.get("auth")).toBe("existing-session");
    }
  );

  test("an older tab cannot consume the latest attempt, which can still finish", async () => {
    const cookies = cookieJar(null, OTHER_ATTEMPT_ID);
    const olderState = callbackState(frontendState(null));
    await expect(
      loginCallbackLoad(
        callbackEvent(`/login/callback?code=older-code&state=${olderState}`, cookies) as never
      )
    ).rejects.toMatchObject({ location: "/login?message=oidc_attempt_rejected" });
    expect(cookies.get(RESUME_COOKIE)).toBeDefined();
    expect(mocks.loginWithOidc).not.toHaveBeenCalled();

    const latestState = frontendState(null, OTHER_ATTEMPT_ID);
    mocks.loginWithOidc.mockResolvedValue({ frontendState: latestState });
    await expect(
      loginCallbackLoad(
        callbackEvent(
          `/login/callback?code=latest-code&state=${callbackState(latestState)}`,
          cookies
        ) as never
      )
    ).rejects.toMatchObject({ location: DEFAULT_LANDING_PAGE });
    expect(mocks.loginWithOidc).toHaveBeenCalledOnce();
  });

  test("a repeated callback after consumption is rejected before a second exchange", async () => {
    const state = frontendState(null);
    const cookies = cookieJar(null);
    const event = callbackEvent(
      `/login/callback?code=authorization-code&state=${callbackState(state)}`,
      cookies
    );
    mocks.loginWithOidc.mockResolvedValue({ frontendState: state });

    await expect(loginCallbackLoad(event as never)).rejects.toMatchObject({
      location: DEFAULT_LANDING_PAGE
    });
    await expect(loginCallbackLoad(event as never)).rejects.toMatchObject({
      location: "/login?message=oidc_attempt_rejected"
    });
    expect(mocks.loginWithOidc).toHaveBeenCalledOnce();
  });

  test("the auth callback alias also rejects a callback without its browser binding", async () => {
    await expect(
      authCallbackLoad(
        callbackEvent(
          `/auth/callback?code=attacker-code&state=${callbackState(frontendState(null))}`
        ) as never
      )
    ).rejects.toMatchObject({ location: "/login?message=oidc_attempt_rejected" });
    expect(mocks.loginWithOidc).not.toHaveBeenCalled();
  });

  test.each([
    ["mobilityguard", mocks.loginWithMobilityguard],
    ["zitadel", mocks.loginWithZitadel]
  ])("%s retains its existing local PKCE login path", async (loginMethod, login) => {
    const state = JSON.stringify({ loginMethod, next: "/spaces" });
    login.mockResolvedValue(true);
    await expect(
      loginCallbackLoad(
        callbackEvent(
          `/login/callback?code=legacy-code&state=${encodeURIComponent(state)}`
        ) as never
      )
    ).rejects.toMatchObject({ location: "/spaces" });
    expect(login).toHaveBeenCalledWith("legacy-code");
    expect(mocks.loginWithOidc).not.toHaveBeenCalled();
  });

  test("an IdP error consumes the cookie and carries only the safe local resume to login", async () => {
    const destination = "/module-login?state=opaque%2526value";
    const providerState = callbackState(frontendState(destination));
    const cookies = cookieJar(destination);
    const debug = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);

    let redirectError: unknown;
    try {
      await loginCallbackLoad(
        callbackEvent(
          `/login/callback?error=temporarily_unavailable&state=${providerState}`,
          cookies
        ) as never
      );
    } catch (caught) {
      redirectError = caught;
    }

    expect(redirectError).toMatchObject({ status: 302 });
    const location = new URL(
      (redirectError as { location: string }).location,
      "https://eneo.example"
    );
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("message")).toBe("oidc_temporarily_unavailable");
    expect(location.searchParams.get("next")).toBe(destination);
    expect(cookies.delete).toHaveBeenCalledWith(RESUME_COOKIE, { path: "/" });
    expect(mocks.loginWithOidc).not.toHaveBeenCalled();
    expect(JSON.stringify([...debug.mock.calls, ...error.mock.calls])).not.toContain(providerState);
  });

  test("a generic OIDC transport failure preserves the safe destination for retry", async () => {
    const destination = "/module-login?state=retry%2526value";
    const providerState = callbackState(frontendState(destination));
    mocks.loginWithOidc.mockResolvedValue(null);
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    let redirectError: unknown;
    try {
      await loginCallbackLoad(
        callbackEvent(
          `/login/callback?code=authorization-code&state=${providerState}`,
          cookieJar(destination)
        ) as never
      );
    } catch (caught) {
      redirectError = caught;
    }

    const location = new URL(
      (redirectError as { location: string }).location,
      "https://eneo.example"
    );
    expect(location.pathname).toBe("/login/failed");
    expect(location.searchParams.get("next")).toBe(destination);
  });
});
