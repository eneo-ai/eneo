// @vitest-environment jsdom
import { act, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeInput, UploadRequest } from "./run-fixtures";

/**
 * A recorded part sent again after the session check failed, through the real
 * session gate: the upload prepares its request with the app's session, and
 * only `fetch` (the session check) and the upload's XHR are stand-ins.
 */

const navigate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/navigate-to", () => ({ navigateTo: navigate }));
vi.mock("./runs-api", () => ({ deleteRuntimeFile: vi.fn(async () => undefined) }));

const probe = (generation = "a") =>
  new Response(null, { status: 204, headers: { "Eneo-Session-Generation": generation } });
const offline = () => Promise.reject(new TypeError("Failed to fetch"));

let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;
let owner: typeof import("@/lib/api/refusal");
let uploads: typeof import("./use-runtime-uploads");
let render: typeof import("@/test/render");

beforeEach(async () => {
  // The session is module state, and a stale one stays stale: each case binds
  // its own, and the upload is loaded with the same modules as that session.
  vi.resetModules();
  vi.clearAllMocks();
  UploadRequest.sent = [];
  fetcher = vi.fn<typeof fetch>(async () => probe());
  vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("XMLHttpRequest", UploadRequest);
  [owner, uploads, render] = await Promise.all([
    import("@/lib/api/refusal"),
    import("./use-runtime-uploads"),
    import("@/test/render")
  ]);
  await owner.initializeBrowserSession();
  fetcher.mockClear();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

type Form = ReturnType<typeof form>;

function form() {
  return render.renderHookInApp(() => uploads.useRuntimeUploads("flow-1", undefined));
}

function record(hook: Form, index: number) {
  const input = makeInput({ step_id: "step-1", accepted_mimetypes: ["audio/webm"] });
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
}

const row = (hook: Form, index = 0) => hook.result.current.uploads["step-1"]![index]!;

/** The session check fails the `failure` way, and that failure is kept. */
async function checkFails(failure: () => Promise<Response>) {
  fetcher.mockImplementation(failure);
  await owner.checkBrowserSession().catch(() => {});
  expect(owner.getSessionSnapshot()).toHaveProperty("checkError");
  fetcher.mockClear();
}

describe("recorded parts waiting when the browser comes back online", () => {
  it("sends them after one shared session check, with no Try again", async () => {
    // The session listens as in the app.
    const stop = owner.listenForSessionResume();
    try {
      const onLine = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
      await checkFails(offline);
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
      const hook = form();
      record(hook, 0);
      record(hook, 1);
      await vi.waitFor(() => {
        for (const index of [0, 1]) {
          expect(row(hook, index)).toMatchObject({
            state: "failed",
            retryable: true,
            nextRetryAt: expect.any(Number)
          });
        }
      });
      // Offline, the parts fail on the kept failure: no check, nothing sent.
      expect(fetcher).not.toHaveBeenCalled();
      expect(UploadRequest.sent).toHaveLength(0);

      onLine.mockReturnValue(true);
      fetcher.mockImplementation(async () => probe());
      await act(async () => {
        window.dispatchEvent(new Event("online"));
      });
      await vi.waitFor(() => expect(UploadRequest.sent).toHaveLength(2));
      expect(fetcher).toHaveBeenCalledTimes(1);
      act(() =>
        UploadRequest.sent.forEach((xhr, index) => xhr.answer(201, { id: `file-${index}` }))
      );
      await vi.waitFor(() => {
        expect(row(hook, 0)).toMatchObject({ state: "done", fileId: "file-0" });
        expect(row(hook, 1)).toMatchObject({ state: "done", fileId: "file-1" });
      });
    } finally {
      stop();
    }
  });
});
