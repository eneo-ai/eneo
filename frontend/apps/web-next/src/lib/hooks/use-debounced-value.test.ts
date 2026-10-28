// @vitest-environment jsdom
import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from "./use-debounced-value";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useDebouncedValue", () => {
  it("starts at the first value and follows a change once the delay has passed", () => {
    let value = "a";
    const { result, rerender } = renderHookInApp(() => useDebouncedValue(value));
    expect(result.current).toBe("a");

    value = "ab";
    rerender();
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1));
    expect(result.current).toBe("a");

    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe("ab");
  });

  it("coalesces rapid changes into one update with the last value", () => {
    let value = "";
    const seen: string[] = [];
    const { rerender } = renderHookInApp(() => {
      const debounced = useDebouncedValue(value, 100);
      if (seen.at(-1) !== debounced) seen.push(debounced);
      return debounced;
    });

    for (const next of ["a", "ab", "abc", "abcd"]) {
      value = next;
      rerender();
      act(() => vi.advanceTimersByTime(60));
    }
    act(() => vi.advanceTimersByTime(100));

    expect(seen).toEqual(["", "abcd"]);
  });
});
