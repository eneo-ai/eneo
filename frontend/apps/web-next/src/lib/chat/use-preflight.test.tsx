// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { deriveContextUsage, usePreflight } from "./use-preflight";

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
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  api.POST.mockReset();
});

it("estimates a bare assistant before typing, but not empty sessions or groups", async () => {
  vi.useFakeTimers();
  api.POST.mockResolvedValue({ data: baseline, response: new Response() });
  const { result, rerender } = renderHook(usePreflight, {
    initialProps: {
      question: "",
      fileIds: [] as string[],
      assistantId: "a1",
      sessionId: null as string | null,
      groupChatId: null as string | null
    }
  });
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(api.POST).toHaveBeenCalledTimes(1);
  expect(api.POST.mock.calls[0]?.[1].body).toMatchObject({ question: "", assistant_id: "a1" });
  expect(result.current).toEqual(baseline);
  rerender({ question: "", fileIds: [], assistantId: "a1", sessionId: "s1", groupChatId: null });
  expect(result.current).toBeNull();
  await act(() => vi.advanceTimersByTimeAsync(400));
  rerender({ question: "", fileIds: [], assistantId: "", sessionId: null, groupChatId: "g1" });
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(api.POST).toHaveBeenCalledTimes(1);
});

it("aborts superseded requests and exposes no estimate from an old request key", async () => {
  vi.useFakeTimers();
  const requests: { signal: AbortSignal; resolve: (value: unknown) => void }[] = [];
  api.POST.mockImplementation(
    (_path, init) => new Promise((resolve) => requests.push({ signal: init.signal, resolve }))
  );
  const { result, rerender, unmount } = renderHook(usePreflight, {
    initialProps: { question: "First", fileIds: [] as string[], assistantId: "a1" }
  });
  await act(() => vi.advanceTimersByTimeAsync(400));
  await act(async () => requests[0]!.resolve({ data: baseline, response: new Response() }));
  expect(result.current).toEqual(baseline);
  rerender({ question: "Second", fileIds: [], assistantId: "a1" });
  expect(result.current).toBeNull();
  expect(requests[0]!.signal.aborted).toBe(true);
  await act(() => vi.advanceTimersByTimeAsync(400));
  rerender({ question: "Third", fileIds: [], assistantId: "a2" });
  expect(requests[1]!.signal.aborted).toBe(true);
  await act(async () => requests[1]!.resolve({ data: baseline, response: new Response() }));
  expect(result.current).toBeNull();
  await act(() => vi.advanceTimersByTimeAsync(400));
  unmount();
  expect(requests[2]!.signal.aborted).toBe(true);
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
