// @vitest-environment jsdom
import { act, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import { usePreflight } from "./use-preflight";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
const estimate = { input_tokens: 10, file_tokens: 0, context_window: 8000 };
beforeEach(() => {
  vi.useFakeTimers();
  api.POST.mockResolvedValue({ data: estimate, response: new Response() });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

it("uses draft choices for the estimate and clears the previous estimate on a model change", async () => {
  let request = {
    question: "Hello",
    fileIds: [],
    assistantId: "assistant",
    settings: { completion_model_id: "model-1" }
  };
  const view = renderHookInApp(() => usePreflight(request));
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(api.POST).toHaveBeenCalledWith(
    "/api/v1/conversations/preflight",
    expect.objectContaining({
      body: expect.objectContaining({ settings: { completion_model_id: "model-1" } })
    })
  );
  expect(view.result.current).toEqual(estimate);
  request = { ...request, settings: { completion_model_id: "model-2" } };
  view.rerender();
  expect(view.result.current).toBeNull();
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
  let request = {
    question: "Hello",
    fileIds: [],
    sessionId: "saved",
    settingsRevision: 3,
    disabled: false
  };
  const view = renderHookInApp(() => usePreflight(request));
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
  request = { ...request, disabled: true };
  view.rerender();
  await act(async () => finish({ data: estimate, response: new Response() }));
  expect(view.result.current).toBeNull();
});

it("keeps the last estimate while the same conversation is typed into", async () => {
  let request = {
    question: "Hello",
    fileIds: [] as string[],
    assistantId: "assistant",
    settings: { completion_model_id: "model-1" }
  };
  const view = renderHookInApp(() => usePreflight(request));
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(view.result.current).toEqual(estimate);
  request = { ...request, question: "Hello there" };
  view.rerender();
  // The previous estimate stays until the new one lands; only the context
  // (model, session, partner) invalidates it at once.
  expect(view.result.current).toEqual(estimate);
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(api.POST).toHaveBeenCalledTimes(2);
  expect(view.result.current).toEqual(estimate);
});
