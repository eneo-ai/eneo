import { describe, expect, it } from "vitest";

import {
  createFlowRuntimeUploadTimeoutController,
  resolveFlowRuntimeUploadIdleTimeoutMs,
  resolveFlowRuntimeUploadInitialTimeoutMs
} from "./runtime-upload-policy";

const policy = {
  min_timeout_seconds: 120,
  seconds_per_mebibyte: 8,
  max_timeout_seconds: 600,
  idle_timeout_seconds: 120
};

describe("runtime upload policy", () => {
  it("uses the minimum timeout for small runtime uploads", () => {
    expect(resolveFlowRuntimeUploadInitialTimeoutMs(1 * 1024 * 1024, policy)).toBe(120_000);
  });

  it("scales the initial timeout from the actual file size", () => {
    expect(resolveFlowRuntimeUploadInitialTimeoutMs(50 * 1024 * 1024, policy)).toBe(400_000);
  });

  it("caps only the initial no-progress timeout for large runtime uploads", () => {
    expect(resolveFlowRuntimeUploadInitialTimeoutMs(200 * 1024 * 1024, policy)).toBe(600_000);
  });

  it("falls back conservatively when older contracts do not expose upload policy", () => {
    expect(resolveFlowRuntimeUploadInitialTimeoutMs(200 * 1024 * 1024, null)).toBe(120_000);
    expect(resolveFlowRuntimeUploadIdleTimeoutMs(null)).toBe(120_000);
  });

  it("falls back conservatively when the upload policy is partial", () => {
    expect(
      resolveFlowRuntimeUploadInitialTimeoutMs(200 * 1024 * 1024, {
        min_timeout_seconds: 120,
        idle_timeout_seconds: 120
      })
    ).toBe(120_000);
  });

  it("uses the policy idle timeout after upload progress has started", () => {
    expect(resolveFlowRuntimeUploadIdleTimeoutMs(policy)).toBe(120_000);
  });

  it("aborts when no upload progress starts within the initial timeout", () => {
    const clock = createFakeClock();
    const abortController = new AbortController();
    const timeouts = [];

    createFlowRuntimeUploadTimeoutController({
      fileSizeBytes: 50 * 1024 * 1024,
      policy,
      abortController,
      onTimeout: (event) => timeouts.push(event),
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout
    });

    expect(clock.current?.timeoutMs).toBe(400_000);
    clock.fireCurrent();

    expect(timeouts).toEqual([{ reason: "not_started", timeoutMs: 400_000 }]);
    expect(abortController.signal.aborted).toBe(true);
  });

  it("switches to the idle timeout after upload progress", () => {
    const clock = createFakeClock();
    const abortController = new AbortController();
    const timeouts = [];
    const controller = createFlowRuntimeUploadTimeoutController({
      fileSizeBytes: 50 * 1024 * 1024,
      policy,
      abortController,
      onTimeout: (event) => timeouts.push(event),
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout
    });

    controller.onProgress({ loaded: 1024, total: 50 * 1024 * 1024, lengthComputable: true });

    expect(clock.current?.timeoutMs).toBe(120_000);
    clock.fireCurrent();
    expect(timeouts).toEqual([{ reason: "stalled", timeoutMs: 120_000 }]);
    expect(abortController.signal.aborted).toBe(true);
  });

  it("uses the server-response timeout after all bytes are sent", () => {
    const clock = createFakeClock();
    const abortController = new AbortController();
    const timeouts = [];
    const controller = createFlowRuntimeUploadTimeoutController({
      fileSizeBytes: 50 * 1024 * 1024,
      policy,
      abortController,
      onTimeout: (event) => timeouts.push(event),
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout
    });

    controller.onProgress({
      loaded: 50 * 1024 * 1024,
      total: 50 * 1024 * 1024,
      lengthComputable: true
    });

    expect(clock.current?.timeoutMs).toBe(120_000);
    clock.fireCurrent();
    expect(timeouts).toEqual([{ reason: "server_not_responding", timeoutMs: 120_000 }]);
    expect(abortController.signal.aborted).toBe(true);
  });

  it("clears the scheduled upload timeout when the caller aborts", () => {
    const clock = createFakeClock();
    const abortController = new AbortController();
    const timeouts = [];

    createFlowRuntimeUploadTimeoutController({
      fileSizeBytes: 50 * 1024 * 1024,
      policy,
      abortController,
      onTimeout: (event) => timeouts.push(event),
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout
    });

    abortController.abort();
    clock.fireCurrent();

    expect(clock.current).toBeNull();
    expect(timeouts).toEqual([]);
  });
});

function createFakeClock() {
  let current = null;
  const setTimeout = (callback, timeoutMs) => {
    current = { callback, timeoutMs, cleared: false };
    return current;
  };
  const clearTimeout = (timer) => {
    timer.cleared = true;
    if (current === timer) current = null;
  };
  return {
    get current() {
      return current;
    },
    setTimeout,
    clearTimeout,
    fireCurrent() {
      const timer = current;
      current = null;
      timer?.callback();
    }
  };
}
