// Tests for the multi-segment recording session controller. The class
// owns the session state machine and orchestrates persistence/upload —
// the heavy lifting that the dialog leans on.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  RecordingSession,
  buildSegmentFilenameBase,
  diffContractSnapshot,
  generateSessionId,
  type RecordingSessionDeps,
  type RecordingSessionEventListeners
} from "./recordingSession";
import { recordingSessionStore, type ContractSnapshot } from "./recordingSessionStore";

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
    uploadSegment: vi.fn(async (file: File) => ({
      ok: true as const,
      fileId: `uploaded-${file.name}`
    })),
    deleteUploadedSegment: vi.fn(async () => undefined),
    ...overrides
  };
}

beforeEach(() => {
  recordingSessionStore.__resetForTests();
});

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
  it("transitions to recording on a successful start", async () => {
    const states: string[] = [];
    const listeners: RecordingSessionEventListeners = {
      onStateChange: (s) => states.push(s)
    };
    const session = new RecordingSession(makeDeps(), listeners);
    const outcome = await session.start({
      flowId: "flow-1",
      stepId: "step-1",
      contractSnapshot: baseSnapshot
    });
    expect(outcome.ok).toBe(true);
    expect(states).toContain("preparing");
    expect(states).toContain("recording");
    session.dispose();
  });

  it("transitions to paused-failed when startSegment rejects", async () => {
    const deps = makeDeps({
      startSegment: vi.fn(async () => ({ ok: false, error: new Error("denied") }))
    });
    const session = new RecordingSession(deps, {});
    const outcome = await session.start({
      flowId: "flow-1",
      stepId: "step-1",
      contractSnapshot: baseSnapshot
    });
    expect(outcome.ok).toBe(false);
    expect(session.summary().state).toBe("paused-failed");
    session.dispose();
  });

  it("marks the session completed on a manual stop", async () => {
    const deps = makeDeps();
    const session = new RecordingSession(deps, {});
    await session.start({
      flowId: "flow-1",
      stepId: "step-1",
      contractSnapshot: baseSnapshot
    });
    await session.onSegmentFinalized({
      blob: new Blob(["data"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      reason: "manual",
      durationMs: 1000
    });
    expect(session.summary().state).toBe("completed");
    expect(session.summary().segments).toHaveLength(1);
    session.dispose();
  });

  it("orders uploaded file ids by capture index, not upload completion", async () => {
    const deps = makeDeps({
      uploadSegment: vi
        .fn()
        .mockResolvedValueOnce({ ok: true, fileId: "first-uploaded" })
        .mockResolvedValueOnce({ ok: true, fileId: "second-uploaded" })
    });
    const session = new RecordingSession(deps, {});
    await session.start({
      flowId: "flow-1",
      stepId: "step-1",
      contractSnapshot: baseSnapshot
    });
    await session.onSegmentFinalized({
      blob: new Blob(["a"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      reason: "manual",
      durationMs: 1000
    });
    // Allow background upload microtasks to settle.
    await Promise.resolve();
    await Promise.resolve();
    const sortedIds = session.uploadedFileIdsSortedBySegmentIndex();
    expect(sortedIds).toEqual(["first-uploaded"]);
    session.dispose();
  });

  it("beginRecordingExternal cancels a queued retry timer when called from reconnecting", async () => {
    vi.useFakeTimers();
    const startSegment = vi
      .fn<RecordingSessionDeps["startSegment"]>()
      .mockResolvedValueOnce({ ok: false, error: new Error("denied") })
      .mockResolvedValue({ ok: true });
    const deps = makeDeps({ startSegment });
    const session = new RecordingSession(deps, {});

    session.beginRecordingExternal({
      flowId: "flow-1",
      stepId: "step-1",
      contractSnapshot: baseSnapshot
    });
    expect(session.summary().state).toBe("recording");

    // Recorder reports a hard failure; session schedules its first retry.
    session.notifyHardFailure();
    expect(session.summary().state).toBe("reconnecting");

    // User clicks Record again before the 1 s backoff fires. The session
    // must take over: cancel the queued retry and resume recording in the
    // SAME session (sessionId must be preserved).
    const sessionIdBeforeRetake = session.summary().sessionId;
    session.beginRecordingExternal({
      flowId: "flow-1",
      stepId: "step-1",
      contractSnapshot: baseSnapshot
    });
    expect(session.summary().state).toBe("recording");
    expect(session.summary().sessionId).toBe(sessionIdBeforeRetake);

    // Fast-forward past every backoff window. The cancelled retry must NOT
    // call startSegment a second time — the bug we're regressing against
    // would have torn down the user's recording mid-clip.
    await vi.advanceTimersByTimeAsync(10_000);
    expect(startSegment).toHaveBeenCalledTimes(0);

    session.dispose();
    vi.useRealTimers();
  });

  it("clears segments and transitions to discarded after discard", async () => {
    const deleteSpy = vi.fn(async () => undefined);
    const deps = makeDeps({ deleteUploadedSegment: deleteSpy });
    const session = new RecordingSession(deps, {});
    await session.start({
      flowId: "flow-1",
      stepId: "step-1",
      contractSnapshot: baseSnapshot
    });
    await session.onSegmentFinalized({
      blob: new Blob(["a"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      reason: "manual",
      durationMs: 1000
    });
    await Promise.resolve();
    await Promise.resolve();
    await session.discard();
    expect(session.summary().state).toBe("discarded");
    expect(session.summary().segments).toEqual([]);
    // Discard cleans up server-side mirror of every uploaded segment so
    // the orphan janitor doesn't have to.
    expect(deleteSpy).toHaveBeenCalled();
  });
});
