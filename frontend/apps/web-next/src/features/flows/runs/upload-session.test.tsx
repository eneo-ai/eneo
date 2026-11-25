// @vitest-environment jsdom
import { act, cleanup, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import { UPLOAD_RETRY_DELAYS_MS } from "./recording/upload-retry";
import { makeInput } from "./run-fixtures";
import { useRuntimeUploads } from "./use-runtime-uploads";

const hooks = vi.hoisted(() => ({
  prepare: vi.fn<({ request }: { request: Request }) => Promise<Request>>(),
  response: vi.fn<(response: Response, url: string) => Promise<void>>()
}));
const navigate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/navigate-to", () => ({ navigateTo: navigate }));
vi.mock("@/lib/api/base", async (original) => ({
  ...(await original<typeof import("@/lib/api/base")>()),
  API_BASE: "",
  onBrowserApiRequest: hooks.prepare,
  onRawRefusal: hooks.response
}));
vi.mock("./runs-api", () => ({ deleteRuntimeFile: vi.fn(async () => undefined) }));

class UploadRequest {
  static sent: UploadRequest[] = [];
  headers = new Headers();
  responseHeaders = new Headers({ "Eneo-Session-Generation": "a", "x-trace-id": "trace-1" });
  status = 0;
  responseText = "";
  upload = { onprogress: null as ((event: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  aborted = false;
  url = "";
  open(_method: string, url: string) {
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers.set(name, value);
  }
  getAllResponseHeaders() {
    return Array.from(this.responseHeaders, ([key, value]) => `${key}: ${value}`).join("\r\n");
  }
  getResponseHeader(name: string) {
    return this.responseHeaders.get(name);
  }
  send() {
    UploadRequest.sent.push(this);
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
  answer(status: number, body: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(body);
    this.onload?.();
  }
}

let session: AbortController;
beforeEach(() => {
  vi.clearAllMocks();
  UploadRequest.sent = [];
  session = new AbortController();
  hooks.prepare.mockImplementation(async ({ request }) => {
    session.signal.throwIfAborted();
    const headers = new Headers(request.headers);
    headers.set("Eneo-Session-Generation", "a");
    return new Request(request, {
      headers,
      signal: AbortSignal.any([request.signal, session.signal])
    });
  });
  hooks.response.mockResolvedValue(undefined);
  vi.stubGlobal("XMLHttpRequest", UploadRequest);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function uploadFiles(count = 1) {
  const hook = renderHookInApp(() => useRuntimeUploads("flow-1", undefined));
  act(() =>
    hook.result.current.add(
      makeInput({ step_id: "step-1" }),
      Array.from(
        { length: count },
        (_, i) => new File(["data"], `${i}.pdf`, { type: "application/pdf" })
      )
    )
  );
  await waitFor(() => expect(UploadRequest.sent).toHaveLength(count));
  return hook;
}

it("uses the shared request and response contract before accepting a runtime file", async () => {
  const hook = await uploadFiles();
  const xhr = UploadRequest.sent[0]!;
  expect(xhr.url).toBe("/api/v1/flows/flow-1/steps/step-1/runtime-files/");
  expect(xhr.headers.get("Eneo-Session-Generation")).toBe("a");
  hooks.response.mockRejectedValueOnce(new Error("Session changed"));
  act(() => xhr.answer(201, { id: "other-session-file" }));
  await waitFor(() => expect(hook.result.current.uploads["step-1"]?.[0]?.state).toBe("failed"));
  expect(hook.result.current.uploads["step-1"]?.[0]?.fileId).toBeUndefined();
  const response = hooks.response.mock.calls[0]![0];
  expect(response.headers.get("Eneo-Session-Generation")).toBe("a");
  expect(response.headers.get("x-trace-id")).toBe("trace-1");
});

it("settles a refused upload and sends its body to the same refusal handler", async () => {
  const hook = await uploadFiles();
  const body = { message: "Session expired", eneo_error_code: 9005 };
  act(() => UploadRequest.sent[0]!.answer(401, body));
  await waitFor(() => expect(hook.result.current.uploads["step-1"]?.[0]?.state).toBe("failed"));
  expect(hook.result.current.uploads["step-1"]?.[0]?.retryable).toBe(false);
  expect(await hooks.response.mock.calls[0]![0].json()).toEqual(body);
});

it("sends a recorded part again when the session check could not reach the server", async () => {
  // Offline, the session check fails with fetch's network error, and every
  // request is prepared against that failure until a check succeeds.
  hooks.prepare.mockRejectedValueOnce(new TypeError("Failed to fetch"));
  const hook = renderHookInApp(() => useRuntimeUploads("flow-1", undefined));
  const input = makeInput({ step_id: "step-1", accepted_mimetypes: ["audio/webm"] });
  act(() =>
    hook.result.current.add(input, [new File(["audio"], "del-1.webm", { type: "audio/webm" })], {
      recording: { sessionId: "rec-1", index: 0, durationMs: 1000, streamed: false },
      label: "Inspelning"
    })
  );
  await waitFor(() => expect(hook.result.current.uploads["step-1"]?.[0]?.state).toBe("failed"));
  const part = hook.result.current.uploads["step-1"]![0]!;
  // It may pass: the part keeps its Try again and is sent again by itself.
  expect(part.retryable).toBe(true);
  expect(part.nextRetryAt).toEqual(expect.any(Number));
  // The row says the network failed, not that something went wrong.
  expect(part.problem).toBe("Filen kom inte fram. Försök igen med knappen, eller ta bort filen.");
  expect(UploadRequest.sent).toHaveLength(0);
});

it("does not send a part again by itself when the server answered its upload without a file", async () => {
  const hook = renderHookInApp(() => useRuntimeUploads("flow-1", undefined));
  const input = makeInput({ step_id: "step-1", accepted_mimetypes: ["audio/webm"] });
  act(() =>
    hook.result.current.add(input, [new File(["audio"], "del-1.webm", { type: "audio/webm" })], {
      recording: { sessionId: "rec-1", index: 0, durationMs: 1000, streamed: false },
      label: "Inspelning"
    })
  );
  await waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
  // The server took the request, but its answer is empty: the file may well be stored.
  const xhr = UploadRequest.sent[0]!;
  xhr.status = 201;
  act(() => xhr.onload?.());
  await waitFor(() => expect(hook.result.current.uploads["step-1"]?.[0]?.state).toBe("failed"));
  const part = hook.result.current.uploads["step-1"]![0]!;
  expect(part.retryable).toBe(false);
  expect(part.nextRetryAt).toBeUndefined();
  act(() => {
    window.dispatchEvent(new Event("online"));
  });
  expect(UploadRequest.sent).toHaveLength(1);
});

it("keeps a recorded part's slot while it waits to be sent again", async () => {
  const hook = renderHookInApp(() => useRuntimeUploads("flow-1", undefined));
  const input = makeInput({ step_id: "step-1", max_files: 2, accepted_mimetypes: ["audio/webm"] });
  const record = (index: number) =>
    act(() =>
      hook.result.current.add(
        input,
        [new File(["audio"], `del-${index}.webm`, { type: "audio/webm" })],
        {
          recording: { sessionId: "rec-1", index, durationMs: 1000, streamed: false },
          label: "Inspelning"
        }
      )
    );
  record(0);
  await waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
  act(() => UploadRequest.sent[0]!.answer(201, { id: "file-1" }));
  record(1);
  await waitFor(() => expect(UploadRequest.sent).toHaveLength(2));
  act(() => UploadRequest.sent[1]!.onerror?.());
  await waitFor(() =>
    expect(hook.result.current.uploads["step-1"]?.[1]).toMatchObject({
      state: "failed",
      retryable: true
    })
  );

  // The part exists nowhere else and is sent again: a picked file does not take its slot.
  act(() =>
    hook.result.current.add(input, [new File(["audio"], "fil.webm", { type: "audio/webm" })])
  );
  expect(hook.result.current.uploads["step-1"]?.[2]).toMatchObject({
    name: "fil.webm",
    state: "failed",
    refused: true
  });
  expect(UploadRequest.sent).toHaveLength(2);
});

it("sends a picked file again only when a recorded part waiting to be sent leaves room", async () => {
  const hook = renderHookInApp(() => useRuntimeUploads("flow-1", undefined));
  const input = makeInput({ step_id: "step-1", max_files: 1, accepted_mimetypes: ["audio/webm"] });
  act(() =>
    hook.result.current.add(input, [new File(["audio"], "fil.webm", { type: "audio/webm" })])
  );
  await waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
  act(() => UploadRequest.sent[0]!.onerror?.());
  await waitFor(() => expect(hook.result.current.uploads["step-1"]?.[0]?.state).toBe("failed"));
  act(() =>
    hook.result.current.add(input, [new File(["audio"], "del-1.webm", { type: "audio/webm" })], {
      recording: { sessionId: "rec-1", index: 0, durationMs: 1000, streamed: false },
      label: "Inspelning"
    })
  );
  await waitFor(() => expect(UploadRequest.sent).toHaveLength(2));
  act(() => UploadRequest.sent[1]!.onerror?.());
  await waitFor(() =>
    expect(hook.result.current.uploads["step-1"]?.[1]).toMatchObject({
      state: "failed",
      retryable: true
    })
  );
  const [picked, part] = hook.result.current.uploads["step-1"]!;

  // The waiting part holds the only slot: the picked file is refused for room.
  act(() => hook.result.current.retry("step-1", picked!.key));
  expect(hook.result.current.uploads["step-1"]?.[0]).toMatchObject({
    state: "failed",
    retryable: false,
    refused: true
  });
  expect(UploadRequest.sent).toHaveLength(2);

  // The part may use its own slot.
  act(() => hook.result.current.retry("step-1", part!.key));
  await waitFor(() => expect(UploadRequest.sent).toHaveLength(3));
  expect(hook.result.current.uploads["step-1"]?.[1]?.state).toBe("uploading");
});

it("aborts outstanding uploads on session change and releases settled request listeners", async () => {
  const hook = await uploadFiles(2);
  act(() => UploadRequest.sent[0]!.answer(201, { id: "file-1" }));
  await waitFor(() => expect(hook.result.current.uploads["step-1"]?.[0]?.state).toBe("done"));
  act(() => session.abort(new DOMException("Session changed", "AbortError")));
  await waitFor(() => expect(UploadRequest.sent[1]!.aborted).toBe(true));
  expect(UploadRequest.sent[0]!.aborted).toBe(false);
  await waitFor(() => expect(hook.result.current.uploads["step-1"]?.[1]?.state).toBe("failed"));
});

it("aborts a removed upload through its local signal", async () => {
  const hook = await uploadFiles();
  const entry = hook.result.current.uploads["step-1"]![0]!;
  act(() => hook.result.current.remove("step-1", entry.key));
  expect(UploadRequest.sent[0]!.aborted).toBe(true);
  expect(hook.result.current.uploads["step-1"]).toEqual([]);
});

it("keeps a recorded part when a file is picked for a step that takes one", async () => {
  const hook = renderHookInApp(() => useRuntimeUploads("flow-1", undefined));
  const input = makeInput({ step_id: "step-1", max_files: 1, accepted_mimetypes: ["audio/webm"] });
  act(() =>
    hook.result.current.add(input, [new File(["audio"], "del-1.webm", { type: "audio/webm" })], {
      recording: { sessionId: "rec-1", index: 0, durationMs: 1000, streamed: false },
      label: "Inspelning"
    })
  );
  await waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
  const recorded = hook.result.current.uploads["step-1"]![0]!;

  act(() =>
    hook.result.current.add(input, [new File(["audio"], "fil.webm", { type: "audio/webm" })])
  );

  expect(UploadRequest.sent[0]!.aborted).toBe(false);
  expect(hook.result.current.fileOf(recorded.key)).not.toBeNull();
  const entries = hook.result.current.uploads["step-1"]!;
  expect(entries[0]).toMatchObject({ key: recorded.key, state: "uploading" });
  expect(entries[1]).toMatchObject({ name: "fil.webm", state: "failed" });
});

describe("a recorded part sent again after the session check failed", () => {
  const probe = (generation = "a") =>
    new Response(null, { status: 204, headers: { "Eneo-Session-Generation": generation } });
  const offline = () => Promise.reject(new TypeError("Failed to fetch"));
  const busy = async () =>
    new Response(JSON.stringify({ message: "Unavailable" }), {
      status: 503,
      headers: { "content-type": "application/json" }
    });

  let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;
  let owner: typeof import("@/lib/api/refusal");

  beforeEach(async () => {
    // The session is the module's state, and a stale one stays stale: each case binds its own.
    vi.resetModules();
    fetcher = vi.fn<typeof fetch>(async () => probe());
    vi.stubGlobal("fetch", fetcher);
    owner = await import("@/lib/api/refusal");
    await owner.initializeBrowserSession();
    // The upload is prepared against that session, as in the app.
    hooks.prepare.mockImplementation(({ request }) => owner.prepareBrowserRequest(request));
  });
  afterEach(() => vi.useRealTimers());

  const part = (hook: Awaited<ReturnType<typeof failedPart>>) =>
    hook.result.current.uploads["step-1"]![0]!;

  /** The session check fails the `failure` way; a recorded part then fails and waits to go again. */
  async function failedPart(failure: () => Promise<Response>) {
    fetcher.mockImplementation(failure);
    await owner.checkBrowserSession().catch(() => {});
    expect(owner.getSessionSnapshot()).toHaveProperty("checkError");
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    // From the same modules as the session.
    const [uploads, render] = await Promise.all([
      import("./use-runtime-uploads"),
      import("@/test/render")
    ]);
    const hook = render.renderHookInApp(() => uploads.useRuntimeUploads("flow-1", undefined));
    const input = makeInput({ step_id: "step-1", accepted_mimetypes: ["audio/webm"] });
    act(() =>
      hook.result.current.add(input, [new File(["audio"], "del-1.webm", { type: "audio/webm" })], {
        recording: { sessionId: "rec-1", index: 0, durationMs: 1000, streamed: false },
        label: "Inspelning"
      })
    );
    await vi.waitFor(() =>
      expect(hook.result.current.uploads["step-1"]?.[0]).toMatchObject({
        state: "failed",
        retryable: true
      })
    );
    return hook;
  }

  /** The server is back, with no `online` event: the next attempt checks once and uploads. */
  async function serverBackThen(
    hook: Awaited<ReturnType<typeof failedPart>>,
    attempt: () => unknown
  ) {
    fetcher.mockImplementation(async () => probe());
    fetcher.mockClear();
    await act(async () => attempt());
    await vi.waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(owner.getSessionSnapshot()).not.toHaveProperty("checkError");
    act(() => UploadRequest.sent[0]!.answer(201, { id: "file-1" }));
    await vi.waitFor(() => expect(part(hook)).toMatchObject({ state: "done", fileId: "file-1" }));
  }

  describe.each([
    ["could not reach the server", offline],
    ["answered 503", busy]
  ])("when the last check %s", (_case, failure) => {
    it("checks the session again before the next timed attempt, then uploads", async () => {
      const hook = await failedPart(failure);
      await serverBackThen(hook, () => vi.advanceTimersByTimeAsync(UPLOAD_RETRY_DELAYS_MS[0]));
    });

    it("checks the session again when Try again is pressed after the timed attempts ran out", async () => {
      const hook = await failedPart(failure);
      // The server stays down through every timed attempt: one check each, nothing sent.
      for (const delay of UPLOAD_RETRY_DELAYS_MS) {
        const checks = fetcher.mock.calls.length;
        await act(() => vi.advanceTimersByTimeAsync(delay));
        await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(checks + 1));
        await vi.waitFor(() => expect(part(hook).state).toBe("failed"));
      }
      expect(part(hook).nextRetryAt).toBeNull();
      expect(UploadRequest.sent).toHaveLength(0);
      await serverBackThen(hook, () => hook.result.current.retry("step-1", part(hook).key));
    });
  });

  it("still ends the page and sends nothing when the check finds another person's session", async () => {
    const hook = await failedPart(offline);
    fetcher.mockImplementation(async () => probe("someone-else"));
    await act(() => vi.advanceTimersByTimeAsync(UPLOAD_RETRY_DELAYS_MS[0]));
    await vi.waitFor(() => expect(owner.getSessionSnapshot().status).toBe("stale"));
    expect(navigate).toHaveBeenCalledWith("/login", { replace: true });
    await vi.waitFor(() => expect(part(hook).state).toBe("failed"));
    expect(part(hook).retryable).toBe(false);
    expect(UploadRequest.sent).toHaveLength(0);
  });
});
