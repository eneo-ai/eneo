import { isRedirect, type Cookies } from "@sveltejs/kit";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { encodeState } from "$lib/features/auth/auth.server";

const state = vi.hoisted(() => ({ env: {} as Record<string, string> }));
vi.mock("$env/dynamic/private", () => ({ env: state.env }));
vi.mock("$lib/core/flags.server", () => ({ getFeatureFlags: async () => ({ newAuth: false }) }));

import { authHandle } from "../../../hooks.server";
import { actions, load } from "./+page.server";
import type { PageServerLoad } from "./$types";

function requestEvent(path: string, method = "GET", body?: URLSearchParams) {
  const values = new Map([
    ["auth", "existing-id-token"],
    ["acc", "existing-access-token"],
    ["PARAGLIDE_LOCALE", "sv"]
  ]);
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
