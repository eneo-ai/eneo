import { DEFAULT_LANDING_PAGE } from "$lib/core/constants";
import { beforeEach, describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getBackendUrl: vi.fn(() => "https://eneo.example"),
  loginWithEneo: vi.fn(),
  getMobilityguardLink: vi.fn(),
  getZitadelLink: vi.fn()
}));

vi.mock("$env/dynamic/private", () => ({ env: {} }));
vi.mock("$lib/core/environment.server", () => ({
  getBackendUrl: mocks.getBackendUrl
}));
vi.mock("$lib/features/auth/eneo.server", () => ({
  loginWithEneo: mocks.loginWithEneo
}));
vi.mock("$lib/features/auth/mobilityguard.server", () => ({
  getMobilityguardLink: mocks.getMobilityguardLink
}));
vi.mock("$lib/features/auth/zitadel.server", () => ({
  getZitadelLink: mocks.getZitadelLink
}));

import { actions, load } from "./+page.server";

describe("login resume", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getBackendUrl.mockReturnValue("https://eneo.example");
    mocks.getMobilityguardLink.mockResolvedValue(undefined);
    mocks.getZitadelLink.mockResolvedValue(undefined);
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

  test("single-tenant OIDC receives the same safe resume state returned to the page", async () => {
    const destination = "/module-login?state=opaque%2526value";
    const fetchFn = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          authorization_url: "https://idp.example/authorize",
          state: "signed-state"
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    const cookies = { set: vi.fn(), delete: vi.fn() };
    const event = {
      url: new URL(`https://eneo.example/login?next=${encodeURIComponent(destination)}`),
      locals: {
        id_token: null,
        featureFlags: {
          newAuth: false,
          federationStatus: {
            has_single_tenant_federation: true,
            has_global_oidc_config: false
          }
        }
      },
      fetch: fetchFn,
      cookies
    };

    const result = await load(event as never);

    const initiateUrl = new URL(String(fetchFn.mock.calls[0][0]));
    expect(initiateUrl.pathname).toBe("/api/v1/auth/initiate");
    expect(initiateUrl.searchParams.get("state")).toBe(result.oidcFrontendState);
    const frontendState = JSON.parse(result.oidcFrontendState);
    expect(frontendState).toEqual({
      loginMethod: "oidc",
      next: destination,
      attemptId: expect.any(String)
    });
    expect(cookies.set).toHaveBeenCalledWith(
      "oidc-login-resume",
      JSON.stringify({ attemptId: frontendState.attemptId, destination }),
      expect.objectContaining({ httpOnly: true, sameSite: "lax" })
    );
  });
});
