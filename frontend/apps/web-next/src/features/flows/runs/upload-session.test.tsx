// @vitest-environment jsdom
import { act, cleanup, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import { makeInput } from "./run-fixtures";
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
