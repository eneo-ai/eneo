import { afterEach, describe, expect, it, vi } from "vitest";

import { withinTime } from "./withinTime";

describe("withinTime", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("answers with the promise's value and leaves no timer behind", async () => {
    vi.useFakeTimers();
    expect(await withinTime(Promise.resolve("in time"), 2_000, null)).toBe("in time");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("answers with the fallback when the promise has not settled in time", async () => {
    vi.useFakeTimers();
    const answer = withinTime(new Promise(() => undefined), 2_000, null);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(await answer).toBeNull();
  });
});
