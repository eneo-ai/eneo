// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { apiErrorFromResponse } from "@/lib/api/errors";
import { renderInApp } from "@/test/render";
import { JobsProvider, useJobs } from "./use-jobs";

const hooks = vi.hoisted(() => ({
  prepare: vi.fn<({ request }: { request: Request }) => Promise<Request>>(),
  response: vi.fn<(response: Response, url: string) => Promise<void>>(),
  failures: [] as unknown[]
}));
vi.mock("@/lib/api/base", async (original) => ({
  ...(await original<typeof import("@/lib/api/base")>()),
  onBrowserApiRequest: hooks.prepare,
  onRawRefusal: hooks.response
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: { GET: vi.fn(async () => ({ data: { items: [] }, response: new Response("{}") })) }
}));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/api/errors", async (original) => ({
  ...(await original<typeof import("@/lib/api/errors")>()),
  getErrorMessage: (error: unknown) => {
    hooks.failures.push(error);
    return "Upload failed";
  }
}));
vi.mock("@/lib/toast", () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));

class UploadRequest extends EventTarget {
  static sent: UploadRequest[] = [];
  headers = new Headers();
  responseHeaders = new Headers({
    "content-type": "application/json",
    "Eneo-Session-Generation": "a"
  });
  status = 202;
  response: unknown = null;
  responseType = "";
  upload = new EventTarget();
  aborted = false;
  open() {}
  setRequestHeader(name: string, value: string) {
    this.headers.set(name, value);
  }
  getAllResponseHeaders() {
    return Array.from(this.responseHeaders, ([key, value]) => `${key}: ${value}`).join("\r\n");
  }
  send() {
    UploadRequest.sent.push(this);
  }
  abort() {
    this.aborted = true;
    this.dispatchEvent(new Event("abort"));
    this.dispatchEvent(new Event("loadend"));
  }
  answer(status: number, body: unknown) {
    this.status = status;
    this.response = body;
    this.dispatchEvent(new Event("load"));
    this.dispatchEvent(new Event("loadend"));
  }
}

let session: AbortController;
beforeEach(() => {
  vi.clearAllMocks();
  hooks.failures.length = 0;
  UploadRequest.sent = [];
  session = new AbortController();
  hooks.prepare.mockImplementation(async ({ request }) => {
    session.signal.throwIfAborted();
    return new Request(request, {
      headers: { "Eneo-Session-Generation": "a" },
      signal: session.signal
    });
  });
  hooks.response.mockResolvedValue(undefined);
  vi.stubGlobal("XMLHttpRequest", UploadRequest);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function Queue({ count = 1 }: { count?: number }) {
  const { queueUploads } = useJobs();
  return (
    <button
      onClick={() =>
        queueUploads(
          "collection",
          Array.from({ length: count }, (_, i) => new File(["data"], `${i}.txt`))
        )
      }
    >
      Upload
    </button>
  );
}

it("prepares XHR headers and checks even successful responses before accepting jobs", async () => {
  const { queryClient } = renderInApp(
    <JobsProvider>
      <Queue />
    </JobsProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
  const xhr = UploadRequest.sent[0]!;
  expect(xhr.headers.get("Eneo-Session-Generation")).toBe("a");
  hooks.response.mockRejectedValueOnce(new Error("Session changed"));
  act(() => xhr.answer(202, { id: "replacement-job", status: "in progress" }));
  await waitFor(() => expect(hooks.failures).toHaveLength(1));
  expect(hooks.response).toHaveBeenCalledTimes(1);
  expect(hooks.response.mock.calls[0]![0].headers.get("Eneo-Session-Generation")).toBe("a");
  expect(queryClient.getQueryData(["jobs"])).toEqual([]);
});

it("passes upload diagnostics through the refusal hook without losing their trace", async () => {
  renderInApp(
    <JobsProvider>
      <Queue />
    </JobsProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
  const xhr = UploadRequest.sent[0]!;
  xhr.responseHeaders.set("x-trace-id", "upload-trace");
  hooks.response.mockImplementationOnce(async (response) => {
    throw apiErrorFromResponse(response, await response.json());
  });
  act(() =>
    xhr.answer(401, { message: "Session expired", eneo_error_code: 9005, error_id: "upload-error" })
  );
  await waitFor(() => expect(hooks.failures).toHaveLength(1));
  expect(hooks.failures[0]).toMatchObject({
    status: 401,
    code: 9005,
    traceId: "upload-trace",
    errorId: "upload-error"
  });
  expect(hooks.response).toHaveBeenCalledTimes(1);
});

it("aborts active uploads and refuses queued uploads after the document becomes stale", async () => {
  renderInApp(
    <JobsProvider>
      <Queue count={7} />
    </JobsProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(UploadRequest.sent).toHaveLength(5));
  act(() => session.abort(new DOMException("Session changed", "AbortError")));
  await waitFor(() => expect(hooks.failures).toHaveLength(7));
  expect(UploadRequest.sent).toHaveLength(5);
  expect(UploadRequest.sent.every((xhr) => xhr.aborted)).toBe(true);
  expect(hooks.response).not.toHaveBeenCalled();
});
