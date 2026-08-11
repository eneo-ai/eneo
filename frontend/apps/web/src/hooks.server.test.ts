import { createClient, EneoError } from "@eneo/eneo-js";
import type { RequestEvent, ResolveOptions } from "@sveltejs/kit";
import { beforeEach, describe, expect, test, vi, type MockInstance } from "vitest";
import { handleError, headerFilterHandle } from "./hooks.server";

const TRACE_ID = "0af7651916cd43dd8448eb211c80319c";

/** The options `headerFilterHandle` hands to SvelteKit's `resolve`. */
async function resolveOptions(): Promise<ResolveOptions> {
  let captured: ResolveOptions | undefined;
  await headerFilterHandle({
    event: {} as RequestEvent,
    resolve: (_event: RequestEvent, options?: ResolveOptions) => {
      captured = options;
      return new Response(null);
    }
  });
  if (!captured) throw new Error("headerFilterHandle did not call resolve");
  return captured;
}

/**
 * Wrap a response the way SvelteKit wraps responses fetched inside a load
 * function: reading a header the `filterSerializedResponseHeaders` option does
 * not allow throws instead of returning the value. Mirrors
 * `@sveltejs/kit/src/runtime/server/page/load_data.js`, including the default
 * filter that rejects everything when the option is not set.
 */
function asLoadFetchResponse(response: Response, options: ResolveOptions): Response {
  const allowed = options.filterSerializedResponseHeaders ?? (() => false);
  const get = response.headers.get.bind(response.headers);
  response.headers.get = (name: string) => {
    const lower = name.toLowerCase();
    const value = get(lower);
    if (value && !lower.startsWith("x-sveltekit-") && !allowed(lower, value)) {
      throw new Error(
        `Failed to get response header "${lower}" — it must be included by the \`filterSerializedResponseHeaders\` option`
      );
    }
    return value;
  };
  return response;
}

/** Run a load-function request against a backend response that fails. */
async function failingLoadFetch(response: Response) {
  const client = createClient({
    baseUrl: "https://backend.test",
    fetch: async () => asLoadFetchResponse(response, await resolveOptions())
  });
  return await client.fetch("/api/v1/spaces/", { method: "get", params: { query: {} } }).then(
    () => undefined,
    (error: unknown) => error
  );
}

const ROUTE_ID = "/(app)/spaces/[spaceId]/chat";

function report(error: unknown) {
  const event = {
    route: { id: ROUTE_ID },
    url: new URL("https://eneo.test/spaces/space-1/chat")
  } as unknown as RequestEvent;
  return handleError({ error, event, status: 500, message: "Internal Error" });
}

describe("headerFilterHandle", () => {
  test("lets the headers the Eneo client reads survive a load-function fetch", async () => {
    const { filterSerializedResponseHeaders: allowed } = await resolveOptions();

    expect(allowed?.("x-trace-id", TRACE_ID)).toBe(true);
    expect(allowed?.("x-correlation-id", TRACE_ID)).toBe(true);
    expect(allowed?.("x-error-code", "9046")).toBe(true);
  });

  test("keeps everything else out of the serialized response", async () => {
    const { filterSerializedResponseHeaders: allowed } = await resolveOptions();

    expect(allowed?.("set-cookie", "auth=secret")).toBe(false);
    expect(allowed?.("authorization", "Bearer token")).toBe(false);
  });
});

describe("handleError", () => {
  let logged: MockInstance<typeof console.error>;

  beforeEach(() => {
    logged = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  test("reports the backend error and its trace id when a load fetch fails", async () => {
    const error = await failingLoadFetch(
      new Response(JSON.stringify({ message: "Space not found", eneo_error_code: 9046 }), {
        status: 404,
        headers: { "x-trace-id": TRACE_ID }
      })
    );

    expect(error).toBeInstanceOf(EneoError);
    await expect(report(error)).resolves.toEqual({
      status: 404,
      message: "Space not found",
      code: 9046,
      traceId: TRACE_ID
    });
  });

  test("logs the failure, so a production 500 is not silent on the server", async () => {
    // SvelteKit stops logging errors itself once handleError is defined.
    const error = await failingLoadFetch(
      new Response(JSON.stringify({ message: "Space not found", eneo_error_code: 9046 }), {
        status: 404,
        headers: { "x-trace-id": TRACE_ID }
      })
    );

    await report(error);

    expect(logged).toHaveBeenCalledWith(
      "server error",
      expect.objectContaining({
        route: ROUTE_ID,
        status: 404,
        code: 9046,
        traceId: TRACE_ID,
        message: "Space not found"
      })
    );
  });

  test("keeps the failure intact when the backend also sends an error code", async () => {
    // The client reads `x-error-code` while parsing the response, well before
    // handleError runs — a blocked read there replaced the whole failure with a
    // CONNECTION error about the header. The symbolic header value must also
    // stay out of `code`, which is compared against the numeric ErrorCodes.
    const error = await failingLoadFetch(
      new Response(JSON.stringify({ message: "Audit session required", eneo_error_code: 9001 }), {
        status: 403,
        headers: { "x-trace-id": TRACE_ID, "x-error-code": "AUDIT_SESSION_REQUIRED" }
      })
    );

    expect(error).toBeInstanceOf(EneoError);
    expect((error as EneoError).stage).toBe("RESPONSE");
    expect((error as EneoError).status).toBe(403);
    expect((error as EneoError).message).toBe("Audit session required");
    expect((error as EneoError).code).toBe(9001);
    expect((error as EneoError).getTraceId()).toBe(TRACE_ID);
  });

  test("survives a 422 whose body is not FastAPI's validation shape", async () => {
    // getReadableMessage() reads through `detail[0]` for 422s; a gateway or an
    // unparseable body leaves no detail array, and throwing there would again
    // replace the failure with an error about reporting it.
    const error = await failingLoadFetch(
      new Response("<html>Bad Gateway</html>", {
        status: 422,
        headers: { "x-trace-id": TRACE_ID }
      })
    );

    await expect(report(error)).resolves.toEqual({
      status: 422,
      message: "A validation error occurred.",
      code: 0,
      traceId: TRACE_ID
    });
  });

  test("reports the backend error even when a header cannot be read", async () => {
    // A trace id is diagnostic metadata. If reading it throws — as it did before
    // the headers were allowed through, and as it still would for a header we
    // have not listed — the real failure must survive anyway.
    const error = new EneoError(
      "Space not found",
      "RESPONSE",
      404,
      9046,
      { message: "Space not found" },
      { endpoint: "GET@/api/v1/spaces/" },
      { get: () => throwHeaderError("x-trace-id") } as unknown as Headers
    );

    await expect(report(error)).resolves.toEqual({
      status: 404,
      message: "Space not found",
      code: 9046,
      traceId: undefined
    });
  });
});

function throwHeaderError(name: string): never {
  throw new Error(
    `Failed to get response header "${name}" — it must be included by the \`filterSerializedResponseHeaders\` option`
  );
}
