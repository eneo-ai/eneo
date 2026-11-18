import { isRedirect, type RequestEvent, type ResolveOptions } from "@sveltejs/kit";
// @ts-expect-error -- untyped internal entry; `sequence` reads its tracing from the request store SvelteKit sets per request.
import { with_request_store } from "@sveltejs/kit/internal/server";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("$env/dynamic/private", () => ({ env: { ENEO_BACKEND_URL: "http://backend.test" } }));
vi.mock("$env/dynamic/public", () => ({ env: {} }));
vi.mock("$lib/paraglide/server", async (importOriginal) => {
  const original = await importOriginal<typeof import("$lib/paraglide/server")>();
  return { ...original, paraglideMiddleware: vi.fn(original.paraglideMiddleware) };
});

const { handle, malformedPathHandle } = await import("./hooks.server");
const { reroute } = await import("./hooks");
const { paraglideMiddleware } = await import("$lib/paraglide/server");

/** Paths SvelteKit cannot decode. */
const MALFORMED = ["/en/%E0%A4%A", "/%ZZ", "/sv/%C0%AF", "/en/spaces/%ZZ"];
/** Valid percent-encoding, including an escaped `%` and `/`, and a bad query. */
const WELL_FORMED = ["/sv/%C3%A5", "/%25ZZ", "/%252F", "/a%2Fb", "/login?q=%ZZ"];

const PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile";
const DESKTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)";

// A made-up `auth` cookie only selects the signed-in branch of the login
// check; it proves no sign-in.
const VISITORS = [
  { name: "without a session cookie", session: false, userAgent: DESKTOP },
  { name: "without a session cookie on a phone", session: false, userAgent: PHONE },
  { name: "with a session cookie", session: true, userAgent: DESKTOP },
  { name: "with a session cookie on a phone", session: true, userAgent: PHONE }
];
type Visitor = (typeof VISITORS)[number];

const LATER_STEP_ERROR = new Error("thrown by a later step");

function requestEvent(path: string, visitor: Visitor) {
  const url = new URL(path, "http://eneo.test");
  return {
    url,
    // What SvelteKit passes when it cannot decode the path: no route.
    route: { id: null },
    params: {},
    locals: {},
    request: new Request(url, { headers: { "user-agent": visitor.userAgent } }),
    cookies: {
      get: (name: string) => (visitor.session && name === "auth" ? "made-up-token" : undefined)
    },
    fetch: vi.fn(async () => Response.json({ has_single_tenant_federation: false })),
    isDataRequest: false,
    isSubRequest: false
  } as unknown as RequestEvent & { fetch: ReturnType<typeof vi.fn> };
}

/** Run the app's real `handle` chain the way SvelteKit does, inside a request store. */
async function runHandle(event: RequestEvent) {
  const resolve = vi.fn<(event: RequestEvent, options?: ResolveOptions) => Response>(() => {
    throw LATER_STEP_ERROR;
  });
  const state = {
    tracing: { record_span: ({ fn }: { fn: (span: unknown) => unknown }) => fn({}) }
  };
  const outcome = await with_request_store({ event, state }, () => handle({ event, resolve })).then(
    (response: Response) => ({ response, error: undefined }),
    (error: unknown) => ({ response: undefined, error })
  );
  return { ...outcome, resolve };
}

beforeEach(() => {
  vi.mocked(paraglideMiddleware).mockClear();
});

describe("handle", () => {
  describe.each(VISITORS)("$name", (visitor) => {
    test.each(MALFORMED)("answers 400 to %s before any other hook runs", async (path) => {
      const event = requestEvent(path, visitor);

      const { response, error, resolve } = await runHandle(event);

      expect(error).toBeUndefined();
      expect(response?.status).toBe(400);
      expect(response?.headers.get("content-type")).toMatch(/^text\/plain/);
      expect(paraglideMiddleware).not.toHaveBeenCalled();
      expect(event.fetch).not.toHaveBeenCalled();
      expect(resolve).not.toHaveBeenCalled();
    });

    test.each(WELL_FORMED)(
      "passes %s on unchanged, and a later throw still propagates",
      async (path) => {
        const event = requestEvent(path, visitor);

        const { response, error, resolve } = await runHandle(event);

        expect(response).toBeUndefined();
        expect(paraglideMiddleware).toHaveBeenCalledOnce();
        if (!visitor.session) {
          // The login check throws its redirect, carrying the path as received.
          expect(isRedirect(error) && error.location).toBe(
            `/login?next=${encodeURIComponent(path)}`
          );
        } else if (visitor.userAgent === PHONE) {
          expect(isRedirect(error) && error.location).toBe("/dashboard");
        } else {
          expect(error).toBe(LATER_STEP_ERROR);
          expect(resolve).toHaveBeenCalledOnce();
          expect(resolve.mock.calls[0][0].url.href).toBe(new URL(path, "http://eneo.test").href);
        }
      }
    );
  });
});

/** Whether the path check lets this pathname through. */
async function accepted(pathname: string) {
  const event = { url: new URL(pathname, "http://eneo.test") } as RequestEvent;
  const response = await malformedPathHandle({ event, resolve: () => new Response("passed") });
  return response.status !== 400;
}

// SvelteKit decodes both the request path and what `reroute` returns, while
// the check sees only the request path. This holds as long as `reroute` never
// turns a decodable path into one that is not, or the reverse (see hooks.ts).
describe("reroute", () => {
  test.each([...MALFORMED, ...WELL_FORMED])("keeps the encoding of %s", async (path) => {
    const url = new URL(path, "http://eneo.test");

    const rerouted = await reroute({ url: new URL(url), fetch });

    expect(rerouted).toBeTypeOf("string");
    expect(await accepted(rerouted as string)).toBe(await accepted(url.pathname));
  });
});
