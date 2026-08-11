import type { Cookies, RequestEvent } from "@sveltejs/kit";
import { describe, expect, test } from "vitest";
import { authenticateUser, clearFrontendCookies } from "./auth.server";

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
