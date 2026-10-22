import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UPLOAD_RETRY_DELAYS_MS, UploadRetries } from "./upload-retry";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(Date.UTC(2026, 9, 22, 12, 0, 0));
});
afterEach(() => vi.useRealTimers());

describe("UploadRetries", () => {
  it("sends a failed part again after growing waits, then leaves it to the person", () => {
    const send = vi.fn<(key: string) => void>();
    const retries = new UploadRetries(send);
    const start = Date.now();
    let elapsed = 0;
    for (const delay of UPLOAD_RETRY_DELAYS_MS) {
      expect(retries.failed("part-1")).toBe(start + elapsed + delay);
      vi.advanceTimersByTime(delay - 1);
      expect(send).toHaveBeenCalledTimes(UPLOAD_RETRY_DELAYS_MS.indexOf(delay));
      vi.advanceTimersByTime(1);
      elapsed += delay;
      expect(send).toHaveBeenLastCalledWith("part-1");
    }
    expect(send).toHaveBeenCalledTimes(UPLOAD_RETRY_DELAYS_MS.length);
    // No automatic attempt is left.
    expect(retries.failed("part-1")).toBeNull();
    vi.advanceTimersByTime(10 * 60_000);
    expect(send).toHaveBeenCalledTimes(UPLOAD_RETRY_DELAYS_MS.length);
  });

  it("brings the next attempt forward when the browser is back online", () => {
    const send = vi.fn<(key: string) => void>();
    const retries = new UploadRetries(send);
    retries.failed("part-1");
    retries.failed("part-2");
    retries.online();
    expect(send.mock.calls).toEqual([["part-1"], ["part-2"]]);
    vi.advanceTimersByTime(UPLOAD_RETRY_DELAYS_MS[0]);
    expect(send).toHaveBeenCalledTimes(2);
    // Online counted as the first attempt: the next wait is the second.
    expect(retries.failed("part-1")).toBe(Date.now() + UPLOAD_RETRY_DELAYS_MS[1]);
  });

  it("starts the waits over after a manual retry and forgets a part that left", () => {
    const send = vi.fn<(key: string) => void>();
    const retries = new UploadRetries(send);
    retries.failed("part-1");
    vi.advanceTimersByTime(UPLOAD_RETRY_DELAYS_MS[0]);
    retries.reset("part-1");
    expect(retries.failed("part-1")).toBe(Date.now() + UPLOAD_RETRY_DELAYS_MS[0]);
    retries.reset("part-1");
    vi.advanceTimersByTime(UPLOAD_RETRY_DELAYS_MS[0]);
    expect(send).toHaveBeenCalledTimes(1);

    retries.failed("part-2");
    retries.dispose();
    vi.advanceTimersByTime(60_000);
    expect(send).toHaveBeenCalledTimes(1);
  });
});
