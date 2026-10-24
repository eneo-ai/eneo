// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useNowAt } from "./use-now-at";

const START = Date.parse("2026-10-21T08:00:00Z");
/** The longest delay a browser timer holds. */
const MAX_DELAY = 2 ** 31 - 1;

function at(ms: number): string {
  return new Date(START + ms).toISOString();
}

function renderNow(deadlines: (string | null | undefined)[]) {
  return renderHook(({ list }) => useNowAt(list), { initialProps: { list: deadlines } });
}

beforeEach(() => {
  vi.useFakeTimers({ now: START });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useNowAt", () => {
  it("reads the time again at each future deadline, earliest first, and then rests", () => {
    const { result } = renderNow([at(5_000), at(1_000)]);
    expect(result.current).toBe(START);
    expect(vi.getTimerCount()).toBe(1);

    act(() => vi.advanceTimersByTime(999));
    expect(result.current).toBe(START);
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe(START + 1_000);

    act(() => vi.advanceTimersByTime(3_999));
    expect(result.current).toBe(START + 1_000);
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe(START + 5_000);

    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(60_000));
    expect(result.current).toBe(START + 5_000);
  });

  it("schedules nothing for past, missing or unreadable deadlines", () => {
    const { result } = renderNow([at(-1_000), at(0), null, undefined, "", "not a time"]);
    expect(result.current).toBe(START);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("reads the time again when the deadlines change, and follows the new ones", () => {
    const { result, rerender } = renderNow([at(10_000)]);
    act(() => vi.advanceTimersByTime(2_000));
    expect(result.current).toBe(START);

    // A deadline that is already past is seen at once.
    rerender({ list: [at(1_000)] });
    expect(result.current).toBe(START + 2_000);
    expect(vi.getTimerCount()).toBe(0);

    rerender({ list: [at(3_000)] });
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(1_000));
    expect(result.current).toBe(START + 3_000);
    // The old deadline's timer went with it.
    act(() => vi.advanceTimersByTime(10_000));
    expect(result.current).toBe(START + 3_000);
  });

  it("keeps the same deadlines' timer when only the list is new", () => {
    const { result, rerender } = renderNow([at(1_000)]);
    act(() => vi.advanceTimersByTime(500));
    rerender({ list: [at(1_000)] });
    expect(result.current).toBe(START);
    act(() => vi.advanceTimersByTime(500));
    expect(result.current).toBe(START + 1_000);
  });

  it("waits for a deadline beyond what one timer holds in steps, until it is due", () => {
    const deadline = MAX_DELAY + 5_000;
    const { result } = renderNow([at(deadline)]);
    act(() => vi.advanceTimersByTime(MAX_DELAY - 1));
    expect(result.current).toBe(START);
    // The clamped timer wakes before the deadline and waits on.
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBeLessThan(START + deadline);
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(4_999));
    expect(result.current).toBeLessThan(START + deadline);
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe(START + deadline);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears its timer when it unmounts", () => {
    const { unmount } = renderNow([at(1_000)]);
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
