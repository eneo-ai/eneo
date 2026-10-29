// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/navigate-to", () => ({ navigateTo: navigate }));
vi.mock("@/lib/api/base", () => import("./base.vite"));

const GENERATION = "Eneo-Session-Generation";
const admitted = (
  body: BodyInit | null,
  generation = "session-a",
  contentType = "application/json"
) => new Response(body, { headers: { [GENERATION]: generation, "content-type": contentType } });
let owner: typeof import("./refusal");
let transport: typeof import("./base.vite");
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/spaces");
  fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(
      new Response(null, { status: 204, headers: { [GENERATION]: "session-a" } })
    );
  vi.stubGlobal("fetch", fetcher);
  owner = await import("./refusal");
  transport = await import("./base.vite");
  await owner.initializeBrowserSession();
  fetcher.mockClear();
});
afterEach(() => vi.unstubAllGlobals());

describe("Vite API transports", () => {
  it("loads public federation discovery without cookies or a session-generation response", async () => {
    const request = await transport.onBrowserApiRequest({
      request: new Request(new URL("/api/v1/auth/federation-status", window.location.href))
    });
    expect(request.credentials).toBe("omit");
    expect(request.headers.has(GENERATION)).toBe(false);
    await expect(
      transport.onBrowserApiResponse({ request, response: new Response("{}") })
    ).resolves.toBeUndefined();
    expect(navigate).not.toHaveBeenCalled();
  });

  it.each([
    ["POST", "/api/v1/auth/federation-status"],
    ["GET", "/api/v1/auth/federation-status/private"]
  ])("keeps %s %s under the authenticated response contract", async (method, path) => {
    const request = await transport.onBrowserApiRequest({
      request: new Request(new URL(path, window.location.href), { method })
    });
    expect(request.headers.get(GENERATION)).toBe("session-a");
    await expect(
      transport.onBrowserApiResponse({ request, response: new Response("{}") })
    ).rejects.toMatchObject({ status: 502 });
  });

  it("prepares raw requests and refuses replacement data before returning it", async () => {
    fetcher.mockResolvedValueOnce(admitted('{"name":"B"}', "session-b"));
    await expect(
      transport.apiFetch("/api/v1/example", { method: "POST", body: "draft" })
    ).rejects.toMatchObject({ code: 9080 });
    const sent = fetcher.mock.calls[0]![0] as Request;
    expect(sent.url).toBe(new URL("/api/v1/example", window.location.href).href);
    expect(sent.headers.get(GENERATION)).toBe("session-a");
    expect(sent.method).toBe("POST");
    expect(await sent.text()).toBe("draft");
    expect(sent.signal.aborted).toBe(true);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("applies the same contract to generated typed calls", async () => {
    // Node's Request has no document base URL; browsers resolve relative URLs.
    const NativeRequest = Request;
    vi.stubGlobal(
      "Request",
      class extends NativeRequest {
        constructor(input: RequestInfo | URL, init?: RequestInit) {
          super(typeof input === "string" ? new URL(input, window.location.href) : input, init);
        }
      }
    );
    const { browserApi } = await import("./browser");
    fetcher.mockResolvedValueOnce(admitted('{"id":"user-a"}'));
    const result = await browserApi.GET("/api/v1/users/me/");
    expect(result.data?.id).toBe("user-a");
    expect((fetcher.mock.calls[0]![0] as Request).headers.get(GENERATION)).toBe("session-a");
    fetcher.mockResolvedValueOnce(admitted('{"id":"user-b"}', "session-b"));
    await expect(browserApi.GET("/api/v1/users/me/")).rejects.toMatchObject({ code: 9080 });
  });

  it("rejects late responses and leaves cancelled query data out of the cache", async () => {
    let finish!: (response: Response) => void;
    fetcher.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const { getQueryClient } = await import("./query");
    const client = getQueryClient();
    const loaded = client.query({
      queryKey: ["private"],
      queryFn: async () => (await transport.apiFetch("/api/v1/private")).json(),
      retry: false
    });
    const settled = Promise.allSettled([loaded]);
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    await expect(owner.handleRefusal(admitted("{}", "session-b"), "/api")).rejects.toMatchObject({
      code: 9080
    });
    finish(admitted('{"private":"late"}'));
    expect((await settled)[0].status).toBe("rejected");
    expect(client.getQueryData(["private"])).toBeUndefined();
    await expect(transport.apiFetch("/api/v1/queued")).rejects.toMatchObject({ code: 9080 });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("preserves caller cancellation as well as session cancellation", async () => {
    const caller = new AbortController();
    fetcher.mockResolvedValueOnce(admitted("{}"));
    await transport.apiFetch("/api/v1/example", { signal: caller.signal });
    const request = fetcher.mock.calls[0]![0] as Request;
    expect(request.signal.aborted).toBe(false);
    caller.abort();
    expect(request.signal.aborted).toBe(true);
  });

  it("sends the generation on SSE and closes without accepting late events or reconnecting", async () => {
    let stream!: ReadableStreamDefaultController<Uint8Array>;
    fetcher.mockResolvedValueOnce(
      admitted(
        new ReadableStream({
          start(controller) {
            stream = controller;
          }
        }),
        "session-a",
        "text/event-stream"
      )
    );
    const source = transport.createApiEventSource("/api/v1/jobs/events/");
    const message = vi.fn();
    source.addEventListener("job", message);
    await vi.waitFor(() => expect(source.readyState).toBe(1));
    expect((fetcher.mock.calls[0]![0] as Request).headers.get(GENERATION)).toBe("session-a");
    const encoder = new TextEncoder();
    stream.enqueue(encoder.encode('event: job\ndata: {"id":"a"}\n\n'));
    await vi.waitFor(() => expect(message).toHaveBeenCalledTimes(1));
    await expect(owner.handleRefusal(admitted("{}", "session-b"), "/api")).rejects.toMatchObject({
      code: 9080
    });
    expect(source.readyState).toBe(2);
    stream.enqueue(encoder.encode('event: job\ndata: {"id":"late"}\n\n'));
    stream.close();
    await Promise.resolve();
    await Promise.resolve();
    expect(message).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledTimes(1);
    source.close();
  });
});
