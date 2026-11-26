import { DEFAULT_LANDING_PAGE } from "$lib/core/constants";
import { beforeEach, describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getBackendUrl: vi.fn(() => "https://eneo.example")
}));

vi.mock("$lib/core/environment.server", () => ({
  getBackendUrl: mocks.getBackendUrl
}));

import { actions, load } from "./+page.server";

const ATTEMPT_COOKIE = "oidc-login-resume";

function cookieJar() {
  const values = new Map<string, string>();
  return {
    get: vi.fn((name: string) => values.get(name)),
    set: vi.fn((name: string, value: string) => values.set(name, value)),
    delete: vi.fn((name: string) => values.delete(name))
  };
}

function mfaEvent(search = "", heldToken: string | null = "held-session-token", next?: string) {
  const form = new FormData();
  if (next !== undefined) form.set("next", next);
  return {
    url: new URL(`https://eneo.example/login/mfa${search}`),
    locals: { id_token: heldToken },
    request: new Request("https://eneo.example/login/mfa", { method: "POST", body: form }),
    fetch: vi.fn(),
    cookies: cookieJar()
  };
}

function signedState(frontendState: string) {
  const payload = btoa(
    JSON.stringify({ frontend_state: frontendState, exp: Math.floor(Date.now() / 1000) + 600 })
  )
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
  return `header.${payload}.signature`;
}

describe("signing in for multi-factor authentication", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getBackendUrl.mockReturnValue("https://eneo.example");
  });

  test("the page keeps a signed-in person where they are and says how the sign-in ended", () => {
    expect(load(mfaEvent("?next=%2Fadmin%2Ffederation") as never)).toEqual({
      next: "/admin/federation",
      end: null,
      correlation: null
    });
    expect(
      load(mfaEvent("?detailCode=mfa_not_met&correlation=abc&next=%2Fspaces%2Fx") as never)
    ).toEqual({ next: "/spaces/x", end: "mfa_not_met", correlation: "abc" });
    // Another reason is not this page's to explain, and an unsafe way back is not offered.
    expect(load(mfaEvent("?detailCode=access_denied&next=%2F%2Fevil.example") as never)).toEqual({
      next: DEFAULT_LANDING_PAGE,
      end: null,
      correlation: null
    });
  });

  test("asks the backend for MFA with the session held, and names no organisation", async () => {
    const event = mfaEvent("", "held-session-token", "/admin/federation");
    event.fetch.mockImplementation(async (input: URL) => {
      const state = signedState(input.searchParams.get("state") ?? "");
      return new Response(
        JSON.stringify({ authorization_url: "https://idp.example/authorize?acr_values=x", state }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    });

    await expect(actions.default!(event as never)).rejects.toMatchObject({
      status: 303,
      location: "https://idp.example/authorize?acr_values=x"
    });

    const [url, init] = event.fetch.mock.calls[0] as [URL, RequestInit];
    expect(url.pathname).toBe("/api/v1/auth/initiate");
    expect(url.searchParams.get("mfa")).toBe("true");
    expect(url.searchParams.has("tenant")).toBe(false);
    expect(init.headers).toEqual({ Authorization: "Bearer held-session-token" });
    // The attempt is bound to this browser and remembers where the person was.
    const attempt = JSON.parse(event.cookies.get(ATTEMPT_COOKIE) ?? "{}");
    expect(attempt.destination).toBe("/admin/federation");
  });

  test("an organisation without a rule ends on the page that says so", async () => {
    const event = mfaEvent("", "held-session-token", "/admin/federation");
    event.fetch.mockResolvedValue(
      new Response(JSON.stringify({ code: "mfa_not_configured" }), {
        status: 409,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    await expect(actions.default!(event as never)).rejects.toMatchObject({
      status: 303,
      location: "/login/mfa?detailCode=mfa_not_configured&next=%2Fadmin%2Ffederation"
    });
    expect(event.cookies.set).not.toHaveBeenCalled();
  });

  test("a sign-in that cannot start says so and leaves the session as it is", async () => {
    const event = mfaEvent();
    event.fetch.mockResolvedValue(
      new Response(JSON.stringify({ code: "oidc_login_unavailable" }), { status: 503 })
    );
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    const result = await actions.default!(event as never);

    expect(result).toMatchObject({ status: 503, data: { failed: true, unavailable: true } });
    expect(event.cookies.set).not.toHaveBeenCalled();
  });

  test("someone who is not signed in signs in the ordinary way", async () => {
    const event = mfaEvent("", null, "/admin/federation");

    await expect(actions.default!(event as never)).rejects.toMatchObject({
      status: 303,
      location: "/login?next=%2Fadmin%2Ffederation"
    });
    expect(event.fetch).not.toHaveBeenCalled();
  });
});
