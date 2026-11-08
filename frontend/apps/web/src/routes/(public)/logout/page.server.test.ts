import { isRedirect, type Cookies } from "@sveltejs/kit";
import { beforeEach, describe, expect, onTestFinished, test, vi } from "vitest";
import { encodeState } from "$lib/features/auth/auth.server";

const state = vi.hoisted(() => ({ env: {} as Record<string, string> }));
vi.mock("$env/dynamic/private", () => ({ env: state.env }));
vi.mock("$lib/core/flags.server", () => ({ getFeatureFlags: async () => ({ newAuth: false }) }));

import { authHandle } from "../../../hooks.server";
import { actions, load } from "./+page.server";
import type { PageServerLoad } from "./$types";

function requestEvent(
  path: string,
  method = "GET",
  body?: URLSearchParams,
  auth: string | null = "existing-id-token"
) {
  const values = new Map([
    ["auth", auth ?? ""],
    ["acc", "existing-access-token"],
    ["PARAGLIDE_LOCALE", "sv"]
  ]);
  if (auth === null) values.delete("auth");
  const cookies: Cookies = {
    get: (name) => values.get(name),
    getAll: () => [...values].map(([name, value]) => ({ name, value })),
    set: (name, value) => {
      values.set(name, value);
    },
    delete: (name) => {
      values.delete(name);
    },
    serialize: (name, value) => `${name}=${value}`
  };
  const url = new URL(path, "https://eneo.example");
  const event = {
    url,
    request: new Request(url, { method, body, headers: { origin: url.origin } }),
    cookies,
    fetch: vi.fn(),
    locals: { id_token: "existing-id-token", featureFlags: { newAuth: false } },
    route: { id: "/(public)/logout" }
  } as unknown as Parameters<PageServerLoad>[0];
  return { event, values };
}

async function allowRedirect(action: () => unknown) {
  try {
    return await action();
  } catch (error) {
    if (!isRedirect(error)) throw error;
    return error;
  }
}

describe("read-only session navigation", () => {
  test.each(["GET", "HEAD"])("%s logout preserves the current session", async (method) => {
    const { event, values } = requestEvent("/logout?message=expired", method);
    await allowRedirect(() => load(event));
    expect(values.get("auth")).toBe("existing-id-token");
    expect(values.get("acc")).toBe("existing-access-token");
  });

  test("a provider callback cannot clear a newly established session", async () => {
    const state = encodeState({ completed: true, message: "logout" });
    const { event, values } = requestEvent(`/logout?state=${state}`);
    event.locals.featureFlags = { ...event.locals.featureFlags, newAuth: true };
    await allowRedirect(() => load(event));
    expect(values.get("auth")).toBe("existing-id-token");
  });

  test.each([
    "/embed/widget-id?clear_cookies=1",
    "/login?clear_cookies=true",
    "/logout?clear_cookies=1",
    "/login/switch-organisation?clear_cookies=1",
    "/embed/widget-id?clear%5Fcookies=true"
  ])("resource GET %s cannot reset cookies through the application hook", async (path) => {
    const { event, values } = requestEvent(path);
    await authHandle({ event, resolve: () => new Response("image response") });
    expect(values.get("auth")).toBe("existing-id-token");
    expect(values.get("acc")).toBe("existing-access-token");
    expect(values.get("PARAGLIDE_LOCALE")).toBe("sv");
  });
});

describe("deliberate session actions", () => {
  beforeEach(() => {
    state.env.PUBLIC_ORIGIN = "https://eneo.example";
    state.env.ZITADEL_INSTANCE_URL = "https://identity.example";
    state.env.ZITADEL_PROJECT_CLIENT_ID = "client-id";
  });

  test.each(["logout", "expired"])(
    "logout clears cookies and preserves the %s message",
    async (message) => {
      const { event, values } = requestEvent(
        "/logout?/logout",
        "POST",
        new URLSearchParams({ message })
      );
      const result = await allowRedirect(() => actions.logout(event));
      expect(result).toMatchObject({ status: 303, location: `/login?message=${message}` });
      expect(values.size).toBe(0);
    }
  );

  test("provider logout keeps its callback, prior token hint and expiry message", async () => {
    const { event, values } = requestEvent(
      "/logout?/logout",
      "POST",
      new URLSearchParams({ message: "expired" })
    );
    event.locals.featureFlags = { ...event.locals.featureFlags, newAuth: true };
    const result = await allowRedirect(() => actions.logout(event));
    expect(isRedirect(result)).toBe(true);
    if (!isRedirect(result)) throw new Error("expected redirect");
    const destination = new URL(result.location);
    expect(destination.origin + destination.pathname).toBe(
      "https://identity.example/oidc/v1/end_session"
    );
    expect(destination.searchParams.get("client_id")).toBe("client-id");
    expect(destination.searchParams.get("post_logout_redirect_uri")).toBe(
      "https://eneo.example/logout"
    );
    expect(destination.searchParams.get("id_token_hint")).toBe("existing-id-token");
    expect(JSON.parse(destination.searchParams.get("state")!)).toEqual({
      completed: true,
      message: "expired"
    });
    expect(values.size).toBe(0);
  });

  test("cookie recovery clears all cookies without signing out of the identity provider", async () => {
    const { event, values } = requestEvent("/logout?/clearCookies", "POST");
    event.locals.featureFlags = { ...event.locals.featureFlags, newAuth: true };
    expect(await allowRedirect(() => actions.clearCookies(event))).toMatchObject({
      status: 303,
      location: "/login"
    });
    expect(values.size).toBe(0);
  });

  test("organisation switching clears only authentication and preserves other cookies", async () => {
    const { event, values } = requestEvent("/logout?/switchOrganisation", "POST");
    event.locals.featureFlags = { ...event.locals.featureFlags, newAuth: true };
    expect(await allowRedirect(() => actions.switchOrganisation(event))).toMatchObject({
      status: 303,
      location: "/login"
    });
    expect([...values]).toEqual([["PARAGLIDE_LOCALE", "sv"]]);
  });

  test("a signed-out provider callback renders its outcome without another logout", () => {
    const { event } = requestEvent(
      `/logout?state=${encodeURIComponent(encodeState({ completed: true, message: "expired" }))}`
    );
    event.locals.id_token = null;
    expect(load(event)).toEqual({ message: "expired", signedIn: false });
  });
});

/** An unsigned token: the frontend only reads its claims. */
function token(claims: Record<string, unknown>) {
  const part = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${part({ alg: "HS256", typ: "JWT" })}.${part(claims)}.signature`;
}

const ENEO_CLAIMS = {
  token_version: 2,
  user_id: "6f1c2a4e-0b7d-4e8f-9a3c-5d2e1f0a9b8c",
  tenant_id: "1e2d3c4b-5a69-4788-9a0b-c1d2e3f4a5b6",
  credential_version: 0,
  sub: "user@example.com",
  exp: 4102444800
};
const SESSION_TOKEN = token({
  ...ENEO_CLAIMS,
  sid: "s".repeat(43),
  session_ref: "0b9f3c1e-2d4a-4b6c-8e7f-9a0b1c2d3e4f"
});
const SIGN_OUT = "https://backend.example/api/v1/users/logout/";
const ACTIONS = ["logout", "switchOrganisation", "clearCookies"] as const;

describe("ending the Eneo session before the cookies", () => {
  beforeEach(() => {
    state.env.PUBLIC_ORIGIN = "https://eneo.example";
    state.env.ENEO_BACKEND_URL = "https://backend.example";
  });

  function signOut(action: (typeof ACTIONS)[number], auth: string | null) {
    const { event, values } = requestEvent(
      `/logout?/${action}`,
      "POST",
      new URLSearchParams({ message: "expired" }),
      auth
    );
    return { event, values, run: () => allowRedirect(() => actions[action](event)) };
  }

  test.each(ACTIONS)("%s ends the session on the backend, then clears", async (action) => {
    const { event, values, run } = signOut(action, SESSION_TOKEN);
    let cookiesWhenSignedOut: Map<string, string> | undefined;
    vi.mocked(event.fetch).mockImplementation(async () => {
      cookiesWhenSignedOut = new Map(values);
      return new Response(null, { status: 204 });
    });

    const result = await run();

    expect(event.fetch).toHaveBeenCalledExactlyOnceWith(SIGN_OUT, {
      method: "POST",
      headers: { Authorization: `Bearer ${SESSION_TOKEN}` },
      signal: expect.any(AbortSignal)
    });
    expect(cookiesWhenSignedOut?.get("auth")).toBe(SESSION_TOKEN);
    expect(isRedirect(result)).toBe(true);
    expect(values.has("auth")).toBe(false);
  });

  test.each(
    ACTIONS.flatMap((action) =>
      (["503", "unreachable", "stalled"] as const).map((failure) => [action, failure] as const)
    )
  )("%s keeps every cookie when the backend cannot confirm (%s)", async (action, failure) => {
    const { event, values, run } = signOut(action, SESSION_TOKEN);
    // The action's deadline, fired by hand: a stalled transport answers only
    // when it is aborted.
    const deadline = new AbortController();
    const timeout = vi.spyOn(AbortSignal, "timeout").mockReturnValue(deadline.signal);
    onTestFinished(() => timeout.mockRestore());
    vi.mocked(event.fetch).mockImplementation(async (_url, init) => {
      if (failure === "unreachable") throw new TypeError("fetch failed");
      if (failure === "stalled") {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
          deadline.abort(new DOMException("The operation timed out.", "TimeoutError"));
        });
      }
      return Response.json({ code: "sign_out_unavailable" }, { status: 503 });
    });
    const before = new Map(values);

    const result = await run();

    expect(result).toMatchObject({
      status: 503,
      data: { signOutFailed: action, message: action === "logout" ? "expired" : "logout" }
    });
    expect(values).toEqual(before);
    // Longer than the backend's own five seconds to confirm the deletion.
    if (failure === "stalled") expect(timeout).toHaveBeenCalledWith(10_000);
  });

  // Tokens without an Eneo session (a provider's ID token may carry an OIDC
  // sid of its own) sign out as before, with no backend to wait for.
  test.each(
    ACTIONS.flatMap((action) => [
      [action, "an Eneo token without a session", token(ENEO_CLAIMS)] as const,
      [
        action,
        "a provider ID token with its own sid",
        token({ iss: "https://identity.example", sub: "subject", sid: "provider-session" })
      ] as const,
      [action, "no token", null] as const
    ])
  )("%s with %s clears without the backend", async (action, _case, auth) => {
    const { event, values, run } = signOut(action, auth);
    vi.mocked(event.fetch).mockRejectedValue(new TypeError("fetch failed"));

    const result = await run();

    expect(event.fetch).not.toHaveBeenCalled();
    expect(isRedirect(result)).toBe(true);
    expect(values.has("auth")).toBe(false);
    expect(values.has("acc")).toBe(false);
  });
});
