// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { clearChatDrafts, useChatDraft } from "./use-chat-draft";

const ME = "tenant-1.user-1";
const SOMEONE_ELSE = "tenant-1.user-2";

beforeEach(() => {
  sessionStorage.clear();
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

it("keeps what was typed for a conversation until it is sent", () => {
  const first = renderHook(() => useChatDraft(ME, "assistant:a1:new"));
  act(() => first.result.current[1]("Hur ansöker jag om bygglov"));
  act(() => void vi.advanceTimersByTime(400));
  first.unmount();

  // Back on the conversation (a navigation, a reload, a discarded tab).
  const again = renderHook(() => useChatDraft(ME, "assistant:a1:new"));
  expect(again.result.current[0]).toBe("Hur ansöker jag om bygglov");

  // Sending empties it, and an empty draft is not kept.
  act(() => again.result.current[1](""));
  act(() => void vi.advanceTimersByTime(400));
  again.unmount();
  expect(renderHook(() => useChatDraft(ME, "assistant:a1:new")).result.current[0]).toBe("");
  expect(sessionStorage.length).toBe(0);
});

it("keeps one draft per conversation", () => {
  const a = renderHook(() => useChatDraft(ME, "assistant:a1:s1"));
  act(() => a.result.current[1]("fråga ett"));
  act(() => void vi.advanceTimersByTime(400));
  expect(renderHook(() => useChatDraft(ME, "assistant:a1:s2")).result.current[0]).toBe("");
  expect(renderHook(() => useChatDraft(ME, "assistant:a1:s1")).result.current[0]).toBe("fråga ett");
});

it("does not restore a sent draft when the new conversation receives its session id", () => {
  const draft = renderHook(({ scope }) => useChatDraft(ME, scope), {
    initialProps: { scope: "assistant:a1:new" }
  });
  act(() => draft.result.current[1]("Frågan som skickas"));
  act(() => void vi.advanceTimersByTime(400));
  act(() => draft.result.current[1](""));
  // Session metadata can arrive before the debounced empty value is persisted.
  draft.rerender({ scope: "assistant:a1:saved" });
  act(() => void vi.advanceTimersByTime(400));
  draft.unmount();
  expect(renderHook(() => useChatDraft(ME, "assistant:a1:new")).result.current[0]).toBe("");
});

it("writes at once when the page is hidden, before the pause is over", () => {
  const view = renderHook(() => useChatDraft(ME, "assistant:a1:new"));
  act(() => view.result.current[1]("halvskriven"));
  Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
  expect(sessionStorage.getItem(`eneo:chat-draft:${ME}|assistant:a1:new`)).toBe("halvskriven");
  Reflect.deleteProperty(document, "visibilityState");
});

it("works as before when storage is blocked", () => {
  const blocked = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const view = renderHook(() => useChatDraft(ME, "assistant:a1:new"));
  expect(view.result.current[0]).toBe("");
  act(() => view.result.current[1]((current) => current + "ok"));
  expect(view.result.current[0]).toBe("ok");
  blocked.mockRestore();
});

it("never gives one account's draft to the next one signing in on the same tab", () => {
  const mine = renderHook(() => useChatDraft(ME, "assistant:a1:new"));
  act(() => mine.result.current[1]("min privata fråga"));
  act(() => void vi.advanceTimersByTime(400));
  mine.unmount();

  // The same shared assistant, another account (or the same user in another organisation).
  expect(renderHook(() => useChatDraft(SOMEONE_ELSE, "assistant:a1:new")).result.current[0]).toBe(
    ""
  );
  expect(
    renderHook(() => useChatDraft("tenant-2.user-1", "assistant:a1:new")).result.current[0]
  ).toBe("");
  // Not only unseen: gone from the tab, so nothing can read it later.
  expect(sessionStorage.getItem(`eneo:chat-draft:${ME}|assistant:a1:new`)).toBeNull();
});

it("drops a draft written before drafts belonged to an account", () => {
  sessionStorage.setItem("eneo:chat-draft:assistant:a1:new", "gammal fråga");
  expect(renderHook(() => useChatDraft(ME, "assistant:a1:new")).result.current[0]).toBe("");
  expect(sessionStorage.getItem("eneo:chat-draft:assistant:a1:new")).toBeNull();
});

it("clears every draft on sign-out and leaves the tab's other values alone", () => {
  const view = renderHook(() => useChatDraft(ME, "assistant:a1:new"));
  act(() => view.result.current[1]("en fråga"));
  act(() => void vi.advanceTimersByTime(400));
  sessionStorage.setItem("something-else", "kvar");

  clearChatDrafts();

  expect(sessionStorage.getItem(`eneo:chat-draft:${ME}|assistant:a1:new`)).toBeNull();
  expect(sessionStorage.getItem("something-else")).toBe("kvar");
});
