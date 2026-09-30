import { DEFAULT_LANDING_PAGE } from "$lib/core/constants";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getBackendUrl: vi.fn(() => "https://eneo.example"),
  loginWithEneo: vi.fn(),
  loginWithOidc: vi.fn(),
  getMobilityguardLink: vi.fn(),
  getZitadelLink: vi.fn(),
  clearMobilityguardCookie: vi.fn(),
  clearZitadelCookie: vi.fn(),
  loginWithMobilityguard: vi.fn(),
  loginWithZitadel: vi.fn()
}));

vi.mock("$env/dynamic/private", () => ({ env: {} }));
vi.mock("$lib/core/environment.server", () => ({
  getBackendUrl: mocks.getBackendUrl
}));
vi.mock("$lib/features/auth/eneo.server", () => ({
  loginWithEneo: mocks.loginWithEneo
}));
vi.mock("$lib/features/auth/mobilityguard.server", () => ({
  getMobilityguardLink: mocks.getMobilityguardLink,
  clearMobilityguardCookie: mocks.clearMobilityguardCookie,
  loginWithMobilityguard: mocks.loginWithMobilityguard
}));
vi.mock("$lib/features/auth/zitadel.server", () => ({
  getZitadelLink: mocks.getZitadelLink,
  clearZitadelCookie: mocks.clearZitadelCookie,
  loginWithZitadel: mocks.loginWithZitadel
}));
vi.mock("$lib/features/auth/oidc.server", () => ({
  loginWithOidc: mocks.loginWithOidc
}));

import { actions, load } from "./+page.server";
import { load as callbackLoad } from "./callback/+page.server";

const ATTEMPT_COOKIE = "oidc-login-resume";

function cookieJar() {
  const values = new Map<string, string>();
  return {
    get: vi.fn((name: string) => values.get(name)),
    set: vi.fn((name: string, value: string) => values.set(name, value)),
    delete: vi.fn((name: string) => values.delete(name))
  };
}

function loginEvent(cookies = cookieJar(), path = "/login", form = new FormData()) {
  return {
    url: new URL(path, "https://eneo.example"),
    locals: {
      id_token: null,
      featureFlags: {
        newAuth: false,
        federationStatus: {
          has_single_tenant_federation: true,
          has_global_oidc_config: false,
          has_multi_tenant_federation: false
        }
      }
    },
    request: new Request("https://eneo.example/login?/oidc", { method: "POST", body: form }),
    fetch: vi.fn(),
    cookies
  };
}

function signedState(frontendState: string, ttl = 600) {
  const payload = btoa(
    JSON.stringify({ frontend_state: frontendState, exp: Math.floor(Date.now() / 1000) + ttl })
  )
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
  return `header.${payload}.signature`;
}

async function initiate(event: ReturnType<typeof loginEvent>, ttl = 600) {
  let frontendState = "";
  let state = "";
  event.fetch.mockImplementation(async (input: URL) => {
    frontendState = input.searchParams.get("state") ?? "";
    state = signedState(frontendState, ttl);
    return new Response(
      JSON.stringify({ authorization_url: "https://idp.example/authorize", state }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  });
  await expect(actions.oidc!(event as never)).rejects.toMatchObject({
    status: 303,
    location: "https://idp.example/authorize"
  });
  return { state, frontendState };
}

describe("login resume", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getBackendUrl.mockReturnValue("https://eneo.example");
    mocks.getMobilityguardLink.mockResolvedValue(undefined);
    mocks.getZitadelLink.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test.each([
    { single: false, global: false, multi: false, available: false },
    { single: true, global: false, multi: false, available: true },
    { single: false, global: true, multi: false, available: true },
    { single: false, global: true, multi: true, available: false },
    { single: true, global: true, multi: true, available: false }
  ])("single-tenant availability respects the active mode: %o", async (mode) => {
    const event = loginEvent();
    event.locals.featureFlags.federationStatus = {
      has_single_tenant_federation: mode.single,
      has_global_oidc_config: mode.global,
      has_multi_tenant_federation: mode.multi
    };
    const result = await load(event as never);
    expect(result.hasSingleTenantOidc).toBe(mode.available);
    expect(result.featureFlags.federationStatus.has_multi_tenant_federation).toBe(mode.multi);
    expect(event.fetch).not.toHaveBeenCalled();
    expect(event.cookies.set).not.toHaveBeenCalled();
    expect(event.cookies.delete).not.toHaveBeenCalled();
  });

  test("username/password preserves nested encoding without a second decode", async () => {
    const destination = "/module-login?state=a%2526b%253Dc";
    const form = new FormData();
    form.set("email", "user@example.com");
    form.set("password", "secret");
    form.set("next", destination);
    mocks.loginWithEneo.mockResolvedValue({ success: true, correlationId: null });
    const cookies = { delete: vi.fn() };

    await expect(
      actions.login!({
        request: new Request("https://eneo.example/login?/login", {
          method: "POST",
          body: form
        }),
        cookies
      } as never)
    ).rejects.toMatchObject({ status: 302, location: destination });
    expect(cookies.delete).toHaveBeenCalledWith("oidc-login-resume", { path: "/" });
  });

  test("a failed username/password login reports the attempt limit's standing", async () => {
    const form = new FormData();
    form.set("email", "user@example.com");
    form.set("password", "wrong");
    mocks.loginWithEneo.mockResolvedValue({
      success: false,
      correlationId: "trace-1",
      attemptsRemaining: 0,
      retryAfterSeconds: 540
    });

    const result = await actions.login!({
      request: new Request("https://eneo.example/login?/login", { method: "POST", body: form }),
      cookies: { delete: vi.fn() }
    } as never);

    expect(result).toMatchObject({
      status: 400,
      data: {
        failed: true,
        correlationId: "trace-1",
        attemptsRemaining: 0,
        retryAfterSeconds: 540
      }
    });
  });

  test("a failure without limit details reports none", async () => {
    const form = new FormData();
    form.set("email", "user@example.com");
    form.set("password", "wrong");
    mocks.loginWithEneo.mockResolvedValue({ success: false, correlationId: null });

    const result = await actions.login!({
      request: new Request("https://eneo.example/login?/login", { method: "POST", body: form }),
      cookies: { delete: vi.fn() }
    } as never);

    expect(result).toMatchObject({
      status: 400,
      data: { failed: true, attemptsRemaining: null, retryAfterSeconds: null }
    });
  });

  test("username/password rejects an external post-login destination", async () => {
    const form = new FormData();
    form.set("email", "user@example.com");
    form.set("password", "secret");
    form.set("next", "//evil.example");
    mocks.loginWithEneo.mockResolvedValue({ success: true, correlationId: null });
    const cookies = { delete: vi.fn() };

    await expect(
      actions.login!({
        request: new Request("https://eneo.example/login?/login", {
          method: "POST",
          body: form
        }),
        cookies
      } as never)
    ).rejects.toMatchObject({ status: 302, location: DEFAULT_LANDING_PAGE });
  });

  test.each(["/login", "/login?message=oidc_invalid_request", "/login?message=oidc_access_denied"])(
    "viewing %s neither starts authentication nor changes another tab's browser binding",
    async (path) => {
      const event = loginEvent(cookieJar(), path);
      event.cookies.set(ATTEMPT_COOKIE, "another-tab-binding");
      event.cookies.set.mockClear();

      const result = await load(event as never);

      expect(result.hasSingleTenantOidc).toBe(true);
      expect(event.fetch).not.toHaveBeenCalled();
      expect(event.cookies.set).not.toHaveBeenCalled();
      expect(event.cookies.delete).not.toHaveBeenCalled();
      expect(event.cookies.get(ATTEMPT_COOKIE)).toBe("another-tab-binding");
    }
  );

  test.each([null, "sundsvall"])(
    "single/multi-tenant initiation with tenant %s binds the actual attempt",
    async (tenant) => {
      const destination = "/module-login?state=opaque%2526value";
      const form = new FormData();
      form.set("next", destination);
      if (tenant !== null) form.set("tenant", tenant);
      const event = loginEvent(cookieJar(), "/login", form);
      const result = await initiate(event);
      const initiateUrl = new URL(String(event.fetch.mock.calls[0][0]));
      expect(initiateUrl.pathname).toBe("/api/v1/auth/initiate");
      expect(initiateUrl.searchParams.get("tenant")).toBe(tenant);
      expect(initiateUrl.searchParams.get("state")).toBe(result.frontendState);
      const frontendState = JSON.parse(result.frontendState);
      expect(frontendState).toEqual({
        loginMethod: "oidc",
        next: destination,
        attemptId: expect.any(String)
      });
      expect(event.cookies.set).toHaveBeenCalledWith(
        "oidc-login-resume",
        expect.any(String),
        expect.objectContaining({ httpOnly: true, sameSite: "lax" })
      );
      const attempt = JSON.parse(event.cookies.get(ATTEMPT_COOKIE) ?? "{}");
      expect(attempt).toEqual({
        attemptId: frontendState.attemptId,
        destination,
        expiresAt: expect.any(Number)
      });
    }
  );

  test("starts a bound attempt without next, using the backend's configured lifetime", async () => {
    let now = Date.now();
    vi.spyOn(Date, "now").mockImplementation(() => now);
    const event = loginEvent();
    const result = await initiate(event, 1800);
    const frontendState = JSON.parse(result.frontendState);
    const attempt = JSON.parse(event.cookies.get(ATTEMPT_COOKIE) ?? "{}");
    expect(frontendState.next).toBeNull();
    expect(attempt).toEqual({
      attemptId: frontendState.attemptId,
      destination: null,
      expiresAt: expect.any(Number)
    });
    expect(event.cookies.set).toHaveBeenCalledWith(
      ATTEMPT_COOKIE,
      expect.any(String),
      expect.objectContaining({ maxAge: 1800 })
    );
    now += 11 * 60 * 1000;
    mocks.loginWithOidc.mockResolvedValue({ frontendState: result.frontendState });
    const url = new URL("https://eneo.example/login/callback");
    url.searchParams.set("code", "long-lifetime-code");
    url.searchParams.set("state", result.state);
    await expect(callbackLoad({ ...event, url } as never)).rejects.toMatchObject({
      status: 302,
      location: DEFAULT_LANDING_PAGE
    });
    expect(mocks.loginWithOidc).toHaveBeenCalledOnce();
  });

  test("an idle login page starts a fresh full-lifetime attempt that can finish", async () => {
    let now = Date.now();
    vi.spyOn(Date, "now").mockImplementation(() => now);
    const event = loginEvent();
    await load(event as never);
    now += 11 * 60 * 1000;

    const result = await initiate(event);
    now += 9 * 60 * 1000;
    mocks.loginWithOidc.mockResolvedValue({ frontendState: result.frontendState });
    const url = new URL("https://eneo.example/login/callback");
    url.searchParams.set("code", "new-code");
    url.searchParams.set("state", result.state);
    await expect(callbackLoad({ ...event, url } as never)).rejects.toMatchObject({
      status: 302,
      location: DEFAULT_LANDING_PAGE
    });
    expect(mocks.loginWithOidc).toHaveBeenCalledWith("new-code", result.state, event.fetch);
  });

  test.each(["mismatch", "no-code", "no-state", "provider-error"])(
    "a %s callback follows its error redirect without invalidating the latest tab",
    async (failure) => {
      const cookies = cookieJar();
      const older = await initiate(loginEvent(cookies));
      const latest = await initiate(loginEvent(cookies));
      const latestCookie = cookies.get(ATTEMPT_COOKIE);
      const event = loginEvent(cookies);
      const url = new URL("https://eneo.example/login/callback");
      if (failure !== "no-code") url.searchParams.set("code", "older-code");
      if (failure !== "no-state") url.searchParams.set("state", older.state);
      if (failure === "provider-error") url.searchParams.set("error", "access_denied");
      let redirectUrl = "";
      try {
        await callbackLoad({ ...event, url } as never);
      } catch (error) {
        if (
          typeof error !== "object" ||
          error === null ||
          !("location" in error) ||
          typeof error.location !== "string"
        )
          throw error;
        redirectUrl = error.location;
      }
      expect(redirectUrl).toMatch(/^\/login\?/);
      await load({ ...event, url: new URL(redirectUrl, event.url) } as never);
      expect(cookies.get(ATTEMPT_COOKIE)).toBe(latestCookie);
      expect(mocks.loginWithOidc).not.toHaveBeenCalled();

      mocks.loginWithOidc.mockResolvedValue({ frontendState: latest.frontendState });
      const latestCallback = new URL("https://eneo.example/login/callback");
      latestCallback.searchParams.set("code", "latest-code");
      latestCallback.searchParams.set("state", latest.state);
      await expect(callbackLoad({ ...event, url: latestCallback } as never)).rejects.toMatchObject({
        status: 302,
        location: DEFAULT_LANDING_PAGE
      });
      expect(mocks.loginWithOidc).toHaveBeenCalledOnce();
    }
  );

  test.each([
    new Response("unavailable", { status: 503 }),
    new Response(JSON.stringify({ authorization_url: "https://idp.example/authorize" }), {
      status: 200
    }),
    new Response(JSON.stringify({ authorization_url: "javascript:bad", state: "invalid-state" }), {
      status: 200
    })
  ])(
    "failed initiation preserves another attempt and returns a recoverable failure",
    async (response) => {
      const event = loginEvent();
      event.cookies.set(ATTEMPT_COOKIE, "another-tab-binding");
      event.cookies.set.mockClear();
      event.fetch.mockResolvedValue(response);
      const result = await actions.oidc!(event as never);
      expect(result).toMatchObject({ status: 503, data: { oidcFailed: true } });
      expect(event.cookies.get(ATTEMPT_COOKIE)).toBe("another-tab-binding");
      expect(event.cookies.set).not.toHaveBeenCalled();
    }
  );

  test("rejects an invalid tenant without contacting the backend or replacing an attempt", async () => {
    const form = new FormData();
    form.set("tenant", "invalid/tenant");
    const event = loginEvent(cookieJar(), "/login", form);
    await expect(actions.oidc!(event as never)).resolves.toMatchObject({ status: 400 });
    expect(event.fetch).not.toHaveBeenCalled();
    expect(event.cookies.set).not.toHaveBeenCalled();
  });

  test("an already authenticated user follows the safe destination without starting another login", async () => {
    const form = new FormData();
    form.set("next", "/module-login?state=opaque%2526value");
    const event = loginEvent(cookieJar(), "/login", form);
    event.cookies.set(ATTEMPT_COOKIE, "another-tab-binding");
    event.cookies.set.mockClear();
    await expect(
      actions.oidc!({ ...event, locals: { ...event.locals, id_token: "current-session" } } as never)
    ).rejects.toMatchObject({ status: 303, location: "/module-login?state=opaque%2526value" });
    expect(event.fetch).not.toHaveBeenCalled();
    expect(event.cookies.set).not.toHaveBeenCalled();
    expect(event.cookies.get(ATTEMPT_COOKIE)).toBe("another-tab-binding");
  });
});
