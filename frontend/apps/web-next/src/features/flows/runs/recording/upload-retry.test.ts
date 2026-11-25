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

  it("sends a part whose automatic attempts are spent once the browser is back online", () => {
    const send = vi.fn<(key: string) => void>();
    const retries = new UploadRetries(send);
    for (const delay of UPLOAD_RETRY_DELAYS_MS) {
      retries.failed("part-1");
      vi.advanceTimersByTime(delay);
    }
    expect(retries.failed("part-1")).toBeNull();
    send.mockClear();

    retries.online();
    expect(send.mock.calls).toEqual([["part-1"]]);
    // Its waits start over, as after "Försök igen": a flapping connection does not strand it.
    expect(retries.failed("part-1")).toBe(Date.now() + UPLOAD_RETRY_DELAYS_MS[0]);
    // Sent once: the next online goes with the new wait, not twice.
    retries.online();
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("starts the waits over when the last timed attempt was on its way as the browser came back online", () => {
    const send = vi.fn<(key: string) => void>();
    const retries = new UploadRetries(send);
    for (const delay of UPLOAD_RETRY_DELAYS_MS) {
      retries.failed("part-1");
      vi.advanceTimersByTime(delay);
    }
    // The last timed attempt is on its way: back online sends nothing twice.
    expect(send).toHaveBeenCalledTimes(UPLOAD_RETRY_DELAYS_MS.length);
    retries.online();
    expect(send).toHaveBeenCalledTimes(UPLOAD_RETRY_DELAYS_MS.length);
    // It fails for a reason that passes: it goes again after the first wait, with no second online.
    expect(retries.failed("part-1")).toBe(Date.now() + UPLOAD_RETRY_DELAYS_MS[0]);
    vi.advanceTimersByTime(UPLOAD_RETRY_DELAYS_MS[0]);
    expect(send).toHaveBeenCalledTimes(UPLOAD_RETRY_DELAYS_MS.length + 1);
  });

  it("starts the waits over when an earlier timed attempt was on its way as the browser came back online", () => {
    const send = vi.fn<(key: string) => void>();
    const retries = new UploadRetries(send);
    retries.failed("part-1");
    vi.advanceTimersByTime(UPLOAD_RETRY_DELAYS_MS[0]);
    retries.failed("part-1");
    vi.advanceTimersByTime(UPLOAD_RETRY_DELAYS_MS[1]);
    expect(send).toHaveBeenCalledTimes(2);
    retries.online();
    expect(send).toHaveBeenCalledTimes(2);
    expect(retries.failed("part-1")).toBe(Date.now() + UPLOAD_RETRY_DELAYS_MS[0]);
  });

  it("sends nothing again when the attempt on its way as the browser came back online uploads or is refused for good", () => {
    const send = vi.fn<(key: string) => void>();
    const retries = new UploadRetries(send);
    retries.failed("part-1");
    retries.failed("part-2");
    vi.advanceTimersByTime(UPLOAD_RETRY_DELAYS_MS[0]);
    expect(send).toHaveBeenCalledTimes(2);
    retries.online();
    expect(send).toHaveBeenCalledTimes(2);
    // Part 1 uploads; part 2 is refused for good, which nothing reports to the retries.
    retries.reset("part-1");
    vi.advanceTimersByTime(10 * 60_000);
    retries.online();
    expect(send).toHaveBeenCalledTimes(2);

    // Refused for good before the browser came back online: back online does not send it either.
    retries.failed("part-3");
    vi.advanceTimersByTime(UPLOAD_RETRY_DELAYS_MS[0]);
    expect(send).toHaveBeenCalledTimes(3);
    retries.online();
    vi.advanceTimersByTime(10 * 60_000);
    expect(send).toHaveBeenCalledTimes(3);
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

    // A part that left after its attempts were spent is not sent when the browser is back online.
    for (const delay of UPLOAD_RETRY_DELAYS_MS) {
      retries.failed("part-3");
      vi.advanceTimersByTime(delay);
    }
    send.mockClear();
    expect(retries.failed("part-3")).toBeNull();
    retries.reset("part-3");
    retries.online();
    expect(send).not.toHaveBeenCalled();
  });
});
