// @vitest-environment jsdom
import { act, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UPLOAD_RETRY_DELAYS_MS } from "./recording/upload-retry";
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
const busy = async () =>
  new Response(JSON.stringify({ message: "Unavailable" }), {
    status: 503,
    headers: { "content-type": "application/json" }
  });
/** A server that never answers: the check ends only when it is aborted. */
const silent = (_: unknown, init?: RequestInit) =>
  new Promise<Response>((_, reject) => {
    const signal = init!.signal!;
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  });
/** The session check's time limit. */
const CHECK_LIMIT_MS = 15_000;
/** The row's own words when the file did not reach the server. */
const NOT_SENT = "Filen kom inte fram. Försök igen med knappen, eller ta bort filen.";

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

it("fails a part whose session check never answers at the check's limit, in the row's own words", async () => {
  await checkFails(busy);
  // The server is back but does not answer: the upload's check waits for it.
  fetcher.mockImplementation(silent);
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  const hook = form();
  record(hook, 0);
  await act(() => vi.advanceTimersByTimeAsync(CHECK_LIMIT_MS - 1));
  expect(row(hook).state).toBe("uploading");
  expect(fetcher).toHaveBeenCalledTimes(1);

  await act(() => vi.advanceTimersByTimeAsync(1));
  await vi.waitFor(() =>
    expect(row(hook)).toMatchObject({
      state: "failed",
      retryable: true,
      nextRetryAt: expect.any(Number)
    })
  );
  expect(row(hook).problem).toBe(NOT_SENT);
  expect(UploadRequest.sent).toHaveLength(0);
});

describe("a recorded part sent again after the session check failed", () => {
  /** The session check fails the `failure` way; a recorded part then fails and waits to go again. */
  async function failedPart(failure: () => Promise<Response>) {
    await checkFails(failure);
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const hook = form();
    record(hook, 0);
    await vi.waitFor(() => expect(row(hook)).toMatchObject({ state: "failed", retryable: true }));
    // In the row's own words, also when the check answered 503.
    expect(row(hook).problem).toBe(NOT_SENT);
    return hook;
  }

  /** The server is back, with no `online` event: the next attempt checks once and uploads. */
  async function serverBackThen(hook: Form, attempt: () => unknown) {
    fetcher.mockImplementation(async () => probe());
    fetcher.mockClear();
    await act(async () => attempt());
    await vi.waitFor(() => expect(UploadRequest.sent).toHaveLength(1));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(owner.getSessionSnapshot()).not.toHaveProperty("checkError");
    act(() => UploadRequest.sent[0]!.answer(201, { id: "file-1" }));
    await vi.waitFor(() => expect(row(hook)).toMatchObject({ state: "done", fileId: "file-1" }));
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
        await vi.waitFor(() => expect(row(hook).state).toBe("failed"));
      }
      expect(row(hook).nextRetryAt).toBeNull();
      expect(UploadRequest.sent).toHaveLength(0);
      await serverBackThen(hook, () => hook.result.current.retry("step-1", row(hook).key));
    });
  });

  it("still ends the page and sends nothing when the check finds another person's session", async () => {
    const hook = await failedPart(offline);
    fetcher.mockImplementation(async () => probe("someone-else"));
    await act(() => vi.advanceTimersByTimeAsync(UPLOAD_RETRY_DELAYS_MS[0]));
    await vi.waitFor(() => expect(owner.getSessionSnapshot().status).toBe("stale"));
    expect(navigate).toHaveBeenCalledWith("/login", { replace: true });
    await vi.waitFor(() => expect(row(hook).state).toBe("failed"));
    expect(row(hook).retryable).toBe(false);
    expect(UploadRequest.sent).toHaveLength(0);
  });
});
