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

const RESUME_COOKIE = "oidc-login-resume";
const ATTEMPT_ID = "11111111-1111-4111-8111-111111111111";

function frontendState(destination: string, attemptId = ATTEMPT_ID): string {
  return JSON.stringify({ loginMethod: "oidc", next: destination, attemptId });
}

function callbackState(state: string): string {
  const payload = btoa(JSON.stringify({ frontend_state: state }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
  return `header.${payload}.signature`;
}

function cookieJar(resumeDestination?: string, attemptId = ATTEMPT_ID) {
  let resume =
    resumeDestination === undefined
      ? undefined
      : JSON.stringify({ attemptId, destination: resumeDestination });
  return {
    get: vi.fn((name: string) => (name === RESUME_COOKIE ? resume : undefined)),
    delete: vi.fn((name: string) => {
      if (name === RESUME_COOKIE) resume = undefined;
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

describe("generic OIDC callback resume", () => {
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
