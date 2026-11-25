// @vitest-environment jsdom
import { act, cleanup, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import { UPLOAD_RETRY_DELAYS_MS } from "./recording/upload-retry";
import { makeInput, UploadRequest } from "./run-fixtures";
import { useRuntimeUploads } from "./use-runtime-uploads";

const hooks = vi.hoisted(() => ({
  prepare: vi.fn<({ request }: { request: Request }) => Promise<Request>>(),
  response: vi.fn<(response: Response, url: string) => Promise<void>>()
}));
vi.mock("@/lib/api/base", async (original) => ({
  ...(await original<typeof import("@/lib/api/base")>()),
  API_BASE: "",
  onBrowserApiRequest: hooks.prepare,
  onRawRefusal: hooks.response
}));
vi.mock("./runs-api", () => ({ deleteRuntimeFile: vi.fn(async () => undefined) }));

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
  // The session check failed with fetch's network error, and so does the
  // request's preparation (offline, the gate keeps that failure without
  // checking again). Through the real gate: upload-session-check.test.tsx.
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

describe("a recorded part whose copy is kept elsewhere", () => {
  const input = makeInput({ step_id: "step-1", accepted_mimetypes: ["audio/webm"] });

  function recordPart() {
    const hook = renderHookInApp(() => useRuntimeUploads("flow-1", undefined));
    act(() =>
      hook.result.current.add(input, [new File(["audio"], "del-1.webm", { type: "audio/webm" })], {
        recording: { sessionId: "rec-1", index: 0, durationMs: 1000, streamed: false },
        label: "Inspelning"
      })
    );
    return hook;
  }
  const row = (hook: ReturnType<typeof recordPart>) => hook.result.current.uploads["step-1"]![0]!;

  it("lets go of the part's file once it is uploaded, and the row stays as it was", async () => {
    const hook = recordPart();
    await waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
    act(() => UploadRequest.sent[0]!.answer(201, { id: "file-1" }));
    await waitFor(() => expect(row(hook)).toMatchObject({ state: "done", fileId: "file-1" }));
    const before = row(hook);
    expect(hook.result.current.fileOf(before.key)).not.toBeNull();

    act(() => hook.result.current.release("step-1", before.key));

    expect(hook.result.current.fileOf(before.key)).toBeNull();
    expect(row(hook)).toEqual(before);
  });

  it("keeps the file of a part that uploads, failed or waits to be sent again", async () => {
    const hook = recordPart();
    await waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
    const { key } = row(hook);
    act(() => hook.result.current.release("step-1", key));
    expect(hook.result.current.fileOf(key)).not.toBeNull();

    act(() => UploadRequest.sent[0]!.onerror?.());
    await waitFor(() => expect(row(hook)).toMatchObject({ state: "failed", retryable: true }));
    act(() => hook.result.current.release("step-1", key));
    expect(hook.result.current.fileOf(key)).not.toBeNull();

    // The kept file is what goes again.
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    await waitFor(() => expect(UploadRequest.sent).toHaveLength(2));
    expect(row(hook).state).toBe("uploading");
  });

  it("keeps the file of a part the core refused", async () => {
    const hook = recordPart();
    await waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
    act(() => UploadRequest.sent[0]!.answer(422, { message: "Refused" }));
    await waitFor(() => expect(row(hook)).toMatchObject({ state: "failed", retryable: false }));
    act(() => hook.result.current.release("step-1", row(hook).key));
    expect(hook.result.current.fileOf(row(hook).key)).not.toBeNull();
  });
});

describe("a recorded part whose attempt is on its way when the browser comes back online", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] }));
  afterEach(() => vi.useRealTimers());

  const part = (hook: { result: { current: ReturnType<typeof useRuntimeUploads> } }) =>
    hook.result.current.uploads["step-1"]![0]!;

  /** The part fails on the network until timed attempt `attempts` is on its way; then the browser is back online. */
  async function onItsWayWhenOnline(attempts: number) {
    const hook = renderHookInApp(() => useRuntimeUploads("flow-1", undefined));
    const input = makeInput({ step_id: "step-1", accepted_mimetypes: ["audio/webm"] });
    act(() =>
      hook.result.current.add(input, [new File(["audio"], "del-1.webm", { type: "audio/webm" })], {
        recording: { sessionId: "rec-1", index: 0, durationMs: 1000, streamed: false },
        label: "Inspelning"
      })
    );
    await vi.waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
    for (const delay of UPLOAD_RETRY_DELAYS_MS.slice(0, attempts)) {
      const sent = UploadRequest.sent.length;
      act(() => UploadRequest.sent.at(-1)!.onerror?.());
      await vi.waitFor(() => expect(part(hook).state).toBe("failed"));
      await act(() => vi.advanceTimersByTimeAsync(delay));
      await vi.waitFor(() => expect(UploadRequest.sent).toHaveLength(sent + 1));
    }
    // Nothing is sent twice: the attempt on its way goes on.
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    expect(UploadRequest.sent).toHaveLength(attempts + 1);
    expect(UploadRequest.sent.at(-1)!.aborted).toBe(false);
    return hook;
  }

  it("goes again by itself when the last timed attempt then runs out of time", async () => {
    const hook = await onItsWayWhenOnline(UPLOAD_RETRY_DELAYS_MS.length);
    // No byte moves: the upload's own time limit ends the attempt.
    await act(() => vi.advanceTimersByTimeAsync(120_000));
    await vi.waitFor(() =>
      expect(part(hook)).toMatchObject({
        state: "failed",
        retryable: true,
        nextRetryAt: expect.any(Number)
      })
    );
    // With no second online event.
    await act(() => vi.advanceTimersByTimeAsync(UPLOAD_RETRY_DELAYS_MS[0]));
    await vi.waitFor(() =>
      expect(UploadRequest.sent).toHaveLength(UPLOAD_RETRY_DELAYS_MS.length + 2)
    );
  });

  it("goes again after the first wait when an earlier timed attempt then fails", async () => {
    const hook = await onItsWayWhenOnline(2);
    act(() => UploadRequest.sent.at(-1)!.onerror?.());
    await vi.waitFor(() => expect(part(hook).state).toBe("failed"));
    await act(() => vi.advanceTimersByTimeAsync(UPLOAD_RETRY_DELAYS_MS[0]));
    await vi.waitFor(() => expect(UploadRequest.sent).toHaveLength(4));
  });

  it.each([
    ["uploads", (xhr: UploadRequest) => xhr.answer(201, { id: "file-1" }), "done"],
    [
      "is refused for good",
      (xhr: UploadRequest) => xhr.answer(422, { message: "Not accepted" }),
      "failed"
    ]
  ] as const)("sends nothing again when that attempt %s", async (_case, settle, state) => {
    const hook = await onItsWayWhenOnline(1);
    act(() => settle(UploadRequest.sent.at(-1)!));
    await vi.waitFor(() => expect(part(hook).state).toBe(state));
    await act(() => vi.advanceTimersByTimeAsync(10 * 60_000));
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    expect(UploadRequest.sent).toHaveLength(2);
  });
});
