// @vitest-environment jsdom
import { act, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import { useRemovalMutation } from "./removal";

let main: HTMLElement;

beforeEach(() => {
  vi.useFakeTimers();
  main = document.createElement("main");
  main.id = "main-content";
  main.tabIndex = -1;
  document.body.append(main);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  document.body.replaceChildren();
});

it("restores focus to the page panel when no list target is available", async () => {
  const { result } = renderHookInApp(() =>
    useRemovalMutation({ mutationFn: async () => {}, refresh: async () => {} })
  );

  await act(() => result.current.mutateAsync());
  act(() => vi.advanceTimersByTime(500));

  expect(document.activeElement).toBe(main);
});

it("resolves the list target after the refresh renders it", async () => {
  const target = { current: null as HTMLElement | null };
  const { result } = renderHookInApp(() =>
    useRemovalMutation({
      mutationFn: async () => {},
      refresh: async () => {},
      focusTarget: target
    })
  );

  await act(() => result.current.mutateAsync());
  const heading = document.createElement("h2");
  heading.tabIndex = -1;
  main.append(heading);
  target.current = heading;
  act(() => vi.advanceTimersByTime(500));

  expect(document.activeElement).toBe(heading);
});

it("does not move focus to a replacement page after the removal page unmounts", async () => {
  const { result, unmount } = renderHookInApp(() =>
    useRemovalMutation({ mutationFn: async () => {}, refresh: async () => {} })
  );

  await act(() => result.current.mutateAsync());
  unmount();
  const replacement = document.createElement("main");
  replacement.id = main.id;
  replacement.tabIndex = -1;
  main.replaceWith(replacement);
  act(() => vi.advanceTimersByTime(500));

  expect(document.activeElement).toBe(document.body);
});

it("lets pending focus checks finish after the document is torn down", async () => {
  const { result, unmount, queryClient } = renderHookInApp(() =>
    useRemovalMutation({ mutationFn: async () => {}, refresh: async () => {} })
  );

  await act(() => result.current.mutateAsync());
  unmount();
  queryClient.clear();
  main.remove();
  vi.stubGlobal("document", undefined);
  try {
    expect(() => vi.advanceTimersByTime(500)).not.toThrow();
  } finally {
    vi.unstubAllGlobals();
  }
});
