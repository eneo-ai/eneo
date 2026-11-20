// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { deriveContextUsage, usePreflight } from "./use-preflight";

type PreflightRequest = Parameters<typeof usePreflight>[0];

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const baseline: Schema<"PreflightResponse"> = {
  input_tokens: 0,
  file_tokens: 0,
  excluded_file_count: 0,
  model_name: "model",
  context_window: 10000,
  context_reserve_tokens: 1000,
  prompt_tokens: 500,
  skill_context_tokens: 200,
  assistant_attachment_tokens: 300
};
const estimate = { ...baseline, input_tokens: 10 };
beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  api.POST.mockReset();
});

function renderPreflight(initialProps: PreflightRequest) {
  return renderHook((props: PreflightRequest) => usePreflight(props), { initialProps });
}

it("estimates a bare assistant before typing, but not empty sessions or groups", async () => {
  api.POST.mockResolvedValue({ data: baseline, response: new Response() });
  const { result, rerender } = renderPreflight({
    question: "",
    fileIds: [],
    assistantId: "a1",
    sessionId: null,
    groupChatId: null
  });
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(api.POST).toHaveBeenCalledTimes(1);
  expect(api.POST.mock.calls[0]?.[1].body).toMatchObject({ question: "", assistant_id: "a1" });
  expect(result.current.estimate).toEqual(baseline);
  rerender({ question: "", fileIds: [], assistantId: "a1", sessionId: "s1", groupChatId: null });
  expect(result.current.estimate).toBeNull();
  await act(() => vi.advanceTimersByTimeAsync(400));
  rerender({ question: "", fileIds: [], assistantId: "", sessionId: null, groupChatId: "g1" });
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(api.POST).toHaveBeenCalledTimes(1);
});

it("aborts superseded requests and exposes no estimate from another partner", async () => {
  const requests: { signal: AbortSignal; resolve: (value: unknown) => void }[] = [];
  api.POST.mockImplementation(
    (_path, init) => new Promise((resolve) => requests.push({ signal: init.signal, resolve }))
  );
  const { result, rerender, unmount } = renderPreflight({
    question: "First",
    fileIds: [],
    assistantId: "a1"
  });
  await act(() => vi.advanceTimersByTimeAsync(400));
  await act(async () => requests[0]!.resolve({ data: baseline, response: new Response() }));
  expect(result.current.estimate).toEqual(baseline);
  rerender({ question: "Second", fileIds: [], assistantId: "a1" });
  expect(result.current.estimate).toBeNull();
  expect(requests[0]!.signal.aborted).toBe(true);
  await act(() => vi.advanceTimersByTimeAsync(400));
  rerender({ question: "Third", fileIds: [], assistantId: "a2" });
  expect(result.current.estimate).toBeNull();
  expect(requests[1]!.signal.aborted).toBe(true);
  await act(async () => requests[1]!.resolve({ data: baseline, response: new Response() }));
  expect(result.current.estimate).toBeNull();
  await act(() => vi.advanceTimersByTimeAsync(400));
  unmount();
  expect(requests[2]!.signal.aborted).toBe(true);
});

it("clears the estimate at once when the partner's saved configuration changes", async () => {
  api.POST.mockResolvedValue({ data: baseline, response: new Response() });
  const { result, rerender } = renderPreflight({
    question: "",
    fileIds: [],
    assistantId: "a1",
    revision: "r1"
  });
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(result.current.estimate).toEqual(baseline);
  rerender({ question: "", fileIds: [], assistantId: "a1", revision: "r2" });
  expect(result.current.estimate).toBeNull();
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(api.POST).toHaveBeenCalledTimes(2);
  expect(api.POST.mock.calls[1]?.[1].body).not.toHaveProperty("revision");
  expect(result.current.estimate).toEqual(baseline);
});

it("uses draft choices for the estimate and clears the previous estimate on a model change", async () => {
  api.POST.mockResolvedValue({ data: estimate, response: new Response() });
  const request: PreflightRequest = {
    question: "Hello",
    fileIds: [],
    assistantId: "assistant",
    settings: { completion_model_id: "model-1" }
  };
  const { result, rerender } = renderPreflight(request);
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(api.POST).toHaveBeenCalledWith(
    "/api/v1/conversations/preflight",
    expect.objectContaining({
      body: expect.objectContaining({ settings: { completion_model_id: "model-1" } })
    })
  );
  expect(result.current.estimate).toEqual(estimate);
  rerender({ ...request, settings: { completion_model_id: "model-2" } });
  expect(result.current.estimate).toBeNull();
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(api.POST).toHaveBeenLastCalledWith(
    "/api/v1/conversations/preflight",
    expect.objectContaining({
      body: expect.objectContaining({ settings: { completion_model_id: "model-2" } })
    })
  );
});

it("uses the saved revision and ignores a late estimate after settings become blocked", async () => {
  let finish!: (value: { data: typeof estimate; response: Response }) => void;
  api.POST.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const request: PreflightRequest = {
    question: "Hello",
    fileIds: [],
    sessionId: "saved",
    settingsRevision: 3,
    disabled: false
  };
  const { result, rerender } = renderPreflight(request);
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(api.POST).toHaveBeenCalledWith(
    "/api/v1/conversations/preflight",
    expect.objectContaining({
      body: expect.objectContaining({
        session_id: "saved",
        settings_revision: 3,
        settings: undefined
      })
    })
  );
  rerender({ ...request, disabled: true });
  await act(async () => finish({ data: estimate, response: new Response() }));
  expect(result.current.estimate).toBeNull();
});

it("invalidates the estimate when text changes in the same conversation", async () => {
  api.POST.mockResolvedValue({ data: estimate, response: new Response() });
  const request: PreflightRequest = {
    question: "Hello",
    fileIds: [],
    assistantId: "assistant",
    settings: { completion_model_id: "model-1" }
  };
  const { result, rerender } = renderPreflight(request);
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(result.current.estimate).toEqual(estimate);
  rerender({ ...request, question: "Hello there" });
  expect(result.current.estimate).toBeNull();
  expect(result.current.pending).toBe(true);
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(api.POST).toHaveBeenCalledTimes(2);
});

it("says when an estimate for the current request is on its way, and only then", async () => {
  vi.useFakeTimers();
  const requests: { resolve: (value: unknown) => void; reject: (error: unknown) => void }[] = [];
  api.POST.mockImplementation(
    () => new Promise((resolve, reject) => requests.push({ resolve, reject }))
  );
  const { result, rerender } = renderHook(usePreflight, {
    initialProps: {
      question: "First",
      fileIds: [] as string[],
      assistantId: "a1",
      sessionId: null as string | null
    }
  });
  // Scheduled, then out.
  expect(result.current.pending).toBe(true);
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(result.current.pending).toBe(true);
  await act(async () => requests[0]!.resolve({ data: baseline, response: new Response() }));
  expect(result.current).toEqual({ estimate: baseline, pending: false });

  // A new key: no old estimate while the new one is on its way.
  rerender({ question: "Second", fileIds: [], assistantId: "a1", sessionId: null });
  expect(result.current).toEqual({ estimate: null, pending: true });
  // A refusal (a 429 among them) ends the wait, with no estimate.
  await act(() => vi.advanceTimersByTimeAsync(400));
  await act(async () => requests[1]!.reject(new Error("Too many requests")));
  expect(result.current).toEqual({ estimate: null, pending: false });

  // No request at all: nothing on its way.
  rerender({ question: "", fileIds: [], assistantId: "a1", sessionId: "s1" });
  expect(result.current).toEqual({ estimate: null, pending: false });
});

it("never warns of an overflow from an earlier request's estimate", async () => {
  vi.useFakeTimers();
  const huge = { ...baseline, input_tokens: 20_000 };
  api.POST.mockResolvedValueOnce({ data: huge, response: new Response() });
  api.POST.mockImplementation(() => new Promise(() => {}));
  const { result, rerender } = renderHook(usePreflight, {
    initialProps: { question: "A very long question", fileIds: [] as string[], assistantId: "a1" }
  });
  await act(() => vi.advanceTimersByTimeAsync(400));
  const usage = () =>
    deriveContextUsage({
      preflight: result.current.estimate,
      lockedInputTokens: 0,
      lockedOutputTokens: 0,
      fallbackContextLimit: 10000
    });
  expect(usage().willExceedContext).toBe(true);
  rerender({ question: "Short", fileIds: [], assistantId: "a1" });
  expect(result.current.pending).toBe(true);
  expect(usage().willExceedContext).toBe(false);
});

it("counts the assistant baseline once and exposes Skills as a subset of its prompt", () => {
  expect(
    deriveContextUsage({
      preflight: baseline,
      lockedInputTokens: 0,
      lockedOutputTokens: 0,
      fallbackContextLimit: 0
    })
  ).toMatchObject({
    assistantPromptTokens: 500,
    assistantAttachmentTokens: 300,
    skillContextTokens: 200,
    usedTokens: 800
  });
});
