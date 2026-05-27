import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MAX_RETRY_ATTEMPTS,
  RETRY_BACKOFF_MS,
  RETRY_WALL_CLOCK_CAP_MS,
  RecordingSession,
  SEGMENT_ROTATION_MS,
  buildSegmentFilenameBase,
  diffContractSnapshot,
  generateSessionId,
  type RecordingSessionDeps,
  type RecordingSessionEventListeners
} from "./recordingSession";
import type { ContractSnapshot } from "./recordingSessionStore";

const baseSnapshot: ContractSnapshot = {
  publishedFlowVersion: 1,
  maxFiles: 10,
  maxFileSizeBytes: 25_000_000,
  acceptedMimetypes: ["audio/webm", "audio/mp4"],
  inputFormat: "audio"
};

function makeDeps(overrides: Partial<RecordingSessionDeps> = {}): RecordingSessionDeps {
  return {
    startSegment: vi.fn(async () => ({ ok: true })) as RecordingSessionDeps["startSegment"],
    stopSegment: vi.fn() as RecordingSessionDeps["stopSegment"],
    ...overrides
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("generateSessionId", () => {
  it("returns a non-empty string id", () => {
    const id = generateSessionId();
    expect(typeof id).toBe("string");
    expect(id.length).toBeGreaterThan(8);
  });

  it("returns distinct ids on consecutive calls", () => {
    expect(generateSessionId()).not.toBe(generateSessionId());
  });

  it("uses the backend-compatible filename character set", () => {
    expect(generateSessionId()).toMatch(/^[0-9a-f-]+$/i);
  });
});

describe("buildSegmentFilenameBase", () => {
  it("encodes session, segment index and capture time in a parseable format", () => {
    const captured = Date.UTC(2026, 3, 30, 12, 34, 56);
    const name = buildSegmentFilenameBase("abcdef-1234", 5, captured);
    expect(name).toBe("recording-abcdef-1234-seg05-2026-04-30T12-34-56-000Z");
  });

  it("zero-pads the segment index to two digits", () => {
    const captured = Date.UTC(2026, 0, 1, 0, 0, 0);
    expect(buildSegmentFilenameBase("s", 0, captured)).toContain("seg00");
    expect(buildSegmentFilenameBase("s", 9, captured)).toContain("seg09");
    expect(buildSegmentFilenameBase("s", 99, captured)).toContain("seg99");
  });
});

describe("diffContractSnapshot", () => {
  it("treats step removal as block-resume", () => {
    const issues = diffContractSnapshot(baseSnapshot, { ...baseSnapshot, inputFormat: null }, []);
    expect(issues).toHaveLength(1);
    expect(issues[0]).toMatchObject({ kind: "step-removed", severity: "block-resume" });
  });

  it("treats input-format change as block-resume", () => {
    const issues = diffContractSnapshot(baseSnapshot, { ...baseSnapshot, inputFormat: "file" }, []);
    expect(issues[0]).toMatchObject({
      kind: "input-format-changed",
      severity: "block-resume"
    });
  });

  it("flags a published-version bump as a warn-level issue", () => {
    const issues = diffContractSnapshot(
      baseSnapshot,
      { ...baseSnapshot, publishedFlowVersion: 2 },
      []
    );
    expect(issues.some((i) => i.kind === "version-bump" && i.severity === "warn")).toBe(true);
  });

  it("blocks submit when the new max-files cap is below the captured segment count", () => {
    const segments = Array.from({ length: 6 }, () => ({ mimeType: "audio/webm", bytes: 1024 }));
    const issues = diffContractSnapshot(baseSnapshot, { ...baseSnapshot, maxFiles: 4 }, segments);
    expect(issues.some((i) => i.kind === "max-files-shrunk" && i.severity === "block-submit")).toBe(
      true
    );
  });

  it("blocks submit when a segment's mime is no longer accepted", () => {
    const issues = diffContractSnapshot(
      baseSnapshot,
      { ...baseSnapshot, acceptedMimetypes: ["audio/mp4"] },
      [{ mimeType: "audio/webm", bytes: 1024 }]
    );
    expect(issues.some((i) => i.kind === "mimes-narrowed" && i.severity === "block-submit")).toBe(
      true
    );
  });

  it("returns no issues when nothing relevant changed", () => {
    expect(diffContractSnapshot(baseSnapshot, baseSnapshot, [])).toEqual([]);
  });
});

describe("RecordingSession lifecycle", () => {
  it("begins external recording and arms recorder rotation without starting capture", () => {
    vi.useFakeTimers();
    const states: string[] = [];
    const startSegment = vi.fn(async () => ({ ok: true as const }));
    const stopSegment = vi.fn();
    const deps = makeDeps({ startSegment, stopSegment });
    const listeners: RecordingSessionEventListeners = {
      onStateChange: (s) => states.push(s)
    };
    const session = new RecordingSession(deps, listeners);

    session.beginRecordingExternal();
    expect(session.summary().state).toBe("recording");
    expect(session.summary().sessionId).toEqual(expect.any(String));
    expect(states).toEqual(["recording"]);
    expect(startSegment).not.toHaveBeenCalled();

    vi.advanceTimersByTime(SEGMENT_ROTATION_MS);
    expect(session.summary().state).toBe("rotating");
    expect(stopSegment).toHaveBeenCalledWith("rotation");
    session.dispose();
  });

  it("retries after a hard failure and auto-recovers when recorder restart succeeds", async () => {
    vi.useFakeTimers();
    const startSegment = vi.fn(async () => ({ ok: true as const }));
    const onAutoRecovered = vi.fn();
    const states: string[] = [];
    const deps = makeDeps({ startSegment });
    const session = new RecordingSession(deps, {
      onAutoRecovered,
      onStateChange: (state) => states.push(state)
    });

    session.beginRecordingExternal();
    session.notifyHardFailure();

    expect(session.summary().state).toBe("reconnecting");
    await vi.advanceTimersByTimeAsync(RETRY_BACKOFF_MS[0]);

    expect(startSegment).toHaveBeenCalledTimes(1);
    expect(session.summary().state).toBe("recording");
    expect(session.summary().retryAttempt).toBe(0);
    expect(onAutoRecovered).toHaveBeenCalledTimes(1);
    expect(states).toEqual(["recording", "reconnecting", "recording"]);
    session.dispose();
  });

  it("moves to paused-failed after retry attempts are exhausted", async () => {
    vi.useFakeTimers();
    const startSegment = vi.fn(async () => ({ ok: false as const, error: new Error("denied") }));
    const onRetryFailed = vi.fn();
    const deps = makeDeps({ startSegment });
    const session = new RecordingSession(deps, { onRetryFailed });

    session.beginRecordingExternal();
    session.notifyHardFailure();

    for (const backoff of RETRY_BACKOFF_MS) {
      await vi.advanceTimersByTimeAsync(backoff);
    }

    expect(startSegment).toHaveBeenCalledTimes(MAX_RETRY_ATTEMPTS);
    expect(session.summary().state).toBe("paused-failed");
    expect(onRetryFailed).toHaveBeenCalledTimes(1);
    session.dispose();
  });

  it("honors the retry wall-clock cap", async () => {
    vi.useFakeTimers();
    let now = 0;
    const startSegment = vi.fn(async () => ({ ok: false as const, error: new Error("denied") }));
    const onRetryFailed = vi.fn();
    const deps = makeDeps({ startSegment });
    const session = new RecordingSession(deps, { onRetryFailed }, { now: () => now });

    session.beginRecordingExternal();
    session.notifyHardFailure();
    now = RETRY_WALL_CLOCK_CAP_MS + 1;
    await vi.advanceTimersByTimeAsync(RETRY_BACKOFF_MS[0]);

    expect(startSegment).toHaveBeenCalledTimes(1);
    expect(session.summary().state).toBe("paused-failed");
    expect(onRetryFailed).toHaveBeenCalledTimes(1);
    session.dispose();
  });

  it("beginRecordingExternal cancels a queued retry timer when called from reconnecting", async () => {
    vi.useFakeTimers();
    const startSegment = vi.fn(async () => ({ ok: true as const }));
    const deps = makeDeps({ startSegment });
    const session = new RecordingSession(deps, {});

    session.beginRecordingExternal();
    expect(session.summary().state).toBe("recording");

    // Recorder reports a hard failure; session schedules its first retry.
    session.notifyHardFailure();
    expect(session.summary().state).toBe("reconnecting");

    // User clicks Record again before the 1 s backoff fires. The session
    // must take over: cancel the queued retry and resume recording in the
    // SAME session (sessionId must be preserved).
    const sessionIdBeforeRetake = session.summary().sessionId;
    session.beginRecordingExternal();
    expect(session.summary().state).toBe("recording");
    expect(session.summary().sessionId).toBe(sessionIdBeforeRetake);
    expect(session.summary().retryAttempt).toBe(0);

    // Fast-forward past every backoff window. The cancelled retry must NOT
    // call startSegment a second time — the bug we're regressing against
    // would have torn down the user's recording mid-clip.
    await vi.advanceTimersByTimeAsync(10_000);
    expect(startSegment).toHaveBeenCalledTimes(0);

    session.dispose();
    vi.useRealTimers();
  });

  it("dispose cancels pending rotation and retry work", async () => {
    vi.useFakeTimers();
    const startSegment = vi.fn(async () => ({ ok: true as const }));
    const stopSegment = vi.fn();
    const deps = makeDeps({ startSegment, stopSegment });
    const session = new RecordingSession(deps, {});

    session.beginRecordingExternal();
    session.notifyHardFailure();
    session.dispose();
    session.dispose();

    await vi.advanceTimersByTimeAsync(RETRY_BACKOFF_MS[0]);
    vi.advanceTimersByTime(SEGMENT_ROTATION_MS);

    expect(startSegment).not.toHaveBeenCalled();
    expect(stopSegment).not.toHaveBeenCalled();
  });
});
