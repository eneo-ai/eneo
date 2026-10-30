// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useChatDraft } from "./use-chat-draft";

beforeEach(() => {
  sessionStorage.clear();
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

it("keeps what was typed for a conversation until it is sent", () => {
  const first = renderHook(() => useChatDraft("assistant:a1:new"));
  act(() => first.result.current[1]("Hur ansöker jag om bygglov"));
  act(() => void vi.advanceTimersByTime(400));
  first.unmount();

  // Back on the conversation (a navigation, a reload, a discarded tab).
  const again = renderHook(() => useChatDraft("assistant:a1:new"));
  expect(again.result.current[0]).toBe("Hur ansöker jag om bygglov");

  // Sending empties it, and an empty draft is not kept.
  act(() => again.result.current[1](""));
  act(() => void vi.advanceTimersByTime(400));
  again.unmount();
  expect(renderHook(() => useChatDraft("assistant:a1:new")).result.current[0]).toBe("");
  expect(sessionStorage.length).toBe(0);
});

it("keeps one draft per conversation", () => {
  const a = renderHook(() => useChatDraft("assistant:a1:s1"));
  act(() => a.result.current[1]("fråga ett"));
  act(() => void vi.advanceTimersByTime(400));
  expect(renderHook(() => useChatDraft("assistant:a1:s2")).result.current[0]).toBe("");
  expect(renderHook(() => useChatDraft("assistant:a1:s1")).result.current[0]).toBe("fråga ett");
});

it("writes at once when the page is hidden, before the pause is over", () => {
  const view = renderHook(() => useChatDraft("assistant:a1:new"));
  act(() => view.result.current[1]("halvskriven"));
  Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
  expect(sessionStorage.getItem("eneo:chat-draft:assistant:a1:new")).toBe("halvskriven");
  Reflect.deleteProperty(document, "visibilityState");
});

it("works as before when storage is blocked", () => {
  const blocked = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const view = renderHook(() => useChatDraft("assistant:a1:new"));
  expect(view.result.current[0]).toBe("");
  act(() => view.result.current[1]((current) => current + "ok"));
  expect(view.result.current[0]).toBe("ok");
  blocked.mockRestore();
});
