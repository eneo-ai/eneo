import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Intric } from "@intric/intric-js";

import {
  bumpSegmentCountInState,
  buildContractSnapshotFromStep,
  clearStepSessionInState,
  composeSegmentFilename,
  emptyRecordingSessionState,
  ensureSessionIdInState,
  makeReuploadFileFromRecord,
  markSegmentUploaded,
  persistRecordingSegment,
  purgeAllSessions,
  purgeSession,
  scanRecoverableSessionsForSteps,
  segmentExtensionFromMime,
  synthesizeUploadedFileFromRecord
} from "./flowRunRecordingSession";
import {
  recordingSessionStore,
  type ContractSnapshot,
  type SegmentRecord
} from "./recordingSessionStore";

const snapshot: ContractSnapshot = {
  publishedFlowVersion: 1,
  maxFiles: 10,
  maxFileSizeBytes: 25_000_000,
  acceptedMimetypes: ["audio/webm"],
  inputFormat: "audio"
};

function makeRecord(overrides: Partial<SegmentRecord> = {}): SegmentRecord {
  return {
    flowId: "flow-1",
    stepId: "step-1",
    sessionId: "abcdef00-0000-0000-0000-000000000000",
    segmentIndex: 0,
    blob: new Blob(["data"], { type: "audio/webm" }),
    mimeType: "audio/webm",
    durationMs: 1000,
    capturedAt: Date.UTC(2026, 3, 30, 12, 0, 0),
    uploadedFileId: null,
    reason: "manual",
    contractSnapshot: snapshot,
    ...overrides
  };
}

beforeEach(() => {
  recordingSessionStore.__resetForTests();
});

afterEach(() => {
  recordingSessionStore.__resetForTests();
});

describe("segmentExtensionFromMime", () => {
  it.each([
    ["audio/webm", "webm"],
    ["audio/webm;codecs=opus", "webm"],
    ["audio/mp4", "m4a"],
    ["audio/ogg;codecs=opus", "ogg"],
    ["audio/mpeg", "mp3"],
    ["video/mp4", "m4a"],
    ["unknown/blob", "blob"]
  ])("maps %s → %s", (mime, expected) => {
    expect(segmentExtensionFromMime(mime)).toBe(expected);
  });
});

describe("composeSegmentFilename", () => {
  it("produces a name parseable by the backend segment regex", () => {
    const name = composeSegmentFilename(makeRecord({ segmentIndex: 4 }));
    expect(name).toMatch(
      /^recording-[0-9a-fA-F-]+-seg04-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d+Z\.webm$/
    );
  });
});

describe("synthesizeUploadedFileFromRecord", () => {
  it("requires an uploadedFileId", () => {
    expect(() => synthesizeUploadedFileFromRecord(makeRecord())).toThrow();
  });

  it("rebuilds an UploadedFile pill from the persisted blob's metadata", () => {
    const file = synthesizeUploadedFileFromRecord(
      makeRecord({ uploadedFileId: "file-123", segmentIndex: 2 })
    );
    expect(file.id).toBe("file-123");
    expect(file.mimetype).toBe("audio/webm");
    expect(file.name).toContain("seg02");
    expect(file.size).toBeGreaterThan(0);
  });
});

describe("makeReuploadFileFromRecord", () => {
  it("preserves blob bytes and mime type", () => {
    const record = makeRecord({
      blob: new Blob(["abcdef"], { type: "audio/mp4" }),
      mimeType: "audio/mp4"
    });
    const file = makeReuploadFileFromRecord(record);
    expect(file.type).toBe("audio/mp4");
    expect(file.size).toBe(6);
  });
});

describe("buildContractSnapshotFromStep", () => {
  it("copies accepted_mimetypes by value so later mutations cannot leak in", () => {
    const original = ["audio/webm"];
    const snap = buildContractSnapshotFromStep(
      {
        step_id: "x",
        step_order: 1,
        label: "x",
        description: null,
        input_format: "audio",
        accepted_mimetypes: original,
        max_files: 3,
        max_file_size_bytes: 100,
        required: true
      } as Parameters<typeof buildContractSnapshotFromStep>[0],
      2
    );
    original.push("audio/ogg");
    expect(snap.acceptedMimetypes).toEqual(["audio/webm"]);
    expect(snap.publishedFlowVersion).toBe(2);
    expect(snap.maxFiles).toBe(3);
  });
});

describe("ensureSessionIdInState", () => {
  it("returns the existing id without mutating when one is already set", () => {
    const original = { "step-1": "existing-sess" };
    const result = ensureSessionIdInState(original, "step-1");
    expect(result.sessionId).toBe("existing-sess");
    expect(result.sessionIdsByStepId).toBe(original);
  });

  it("generates a fresh id for a step that hasn't recorded yet", () => {
    const result = ensureSessionIdInState({}, "step-1");
    expect(result.sessionIdsByStepId["step-1"]).toBe(result.sessionId);
    expect(result.sessionId.length).toBeGreaterThan(8);
  });
});

describe("bumpSegmentCountInState", () => {
  it("returns a 0 index for the first call and increments thereafter", () => {
    const first = bumpSegmentCountInState({}, "step-1");
    expect(first.segmentIndex).toBe(0);
    const second = bumpSegmentCountInState(first.segmentCountsByStepId, "step-1");
    expect(second.segmentIndex).toBe(1);
    const third = bumpSegmentCountInState(second.segmentCountsByStepId, "step-1");
    expect(third.segmentIndex).toBe(2);
  });
});

describe("clearStepSessionInState", () => {
  it("removes per-step entries but leaves other steps untouched", () => {
    const state = {
      ...emptyRecordingSessionState(),
      sessionIdsByStepId: { a: "sa", b: "sb" },
      segmentCountsByStepId: { a: 2, b: 1 },
      resumeHintsByStepId: { a: [], b: [] },
      resumePromptStepId: "a",
      resumeBusyStepId: "a"
    };
    const next = clearStepSessionInState(state, "a");
    expect(next.sessionIdsByStepId).toEqual({ b: "sb" });
    expect(next.segmentCountsByStepId).toEqual({ b: 1 });
    expect(next.resumeHintsByStepId).toEqual({ b: [] });
    expect(next.resumePromptStepId).toBeNull();
    expect(next.resumeBusyStepId).toBeNull();
  });
});

describe("persistRecordingSegment + markSegmentUploaded", () => {
  it("writes a record then patches its uploadedFileId", async () => {
    const result = await persistRecordingSegment({
      flowId: "flow-1",
      stepId: "step-1",
      sessionId: "sess-A",
      segmentIndex: 0,
      blob: new Blob(["bytes"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      reason: "manual",
      capturedAt: Date.now(),
      durationMs: 1000,
      contractSnapshot: snapshot
    });
    expect(typeof result.degraded).toBe("boolean");

    await markSegmentUploaded({
      flowId: "flow-1",
      stepId: "step-1",
      sessionId: "sess-A",
      segmentIndex: 0,
      uploadedFileId: "file-XYZ"
    });
    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records[0]?.uploadedFileId).toBe("file-XYZ");
  });
});

describe("scanRecoverableSessionsForSteps", () => {
  it("returns hints keyed by stepId for steps with persisted segments", async () => {
    await persistRecordingSegment({
      flowId: "flow-1",
      stepId: "step-A",
      sessionId: "sess-A",
      segmentIndex: 0,
      blob: new Blob(["data"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      reason: "manual",
      capturedAt: Date.now(),
      durationMs: 1000,
      contractSnapshot: snapshot
    });
    const hints = await scanRecoverableSessionsForSteps({
      flowId: "flow-1",
      steps: [
        {
          step_id: "step-A",
          step_order: 1,
          label: "",
          description: null,
          input_format: "audio",
          accepted_mimetypes: [],
          max_files: null,
          max_file_size_bytes: null,
          required: false
        } as Parameters<typeof scanRecoverableSessionsForSteps>[0]["steps"][number],
        {
          step_id: "step-B",
          step_order: 2,
          label: "",
          description: null,
          input_format: "audio",
          accepted_mimetypes: [],
          max_files: null,
          max_file_size_bytes: null,
          required: false
        } as Parameters<typeof scanRecoverableSessionsForSteps>[0]["steps"][number]
      ]
    });
    expect(hints["step-A"]?.length).toBe(1);
    expect(hints["step-B"]).toBeUndefined();
  });
});

describe("purgeSession", () => {
  it("calls intric.files.delete for uploaded segments and removes the IDB entry", async () => {
    const deleteSpy = vi.fn(async () => undefined);
    const intric = { files: { delete: deleteSpy } } as unknown as Intric;

    await persistRecordingSegment({
      flowId: "flow-1",
      stepId: "step-1",
      sessionId: "sess-A",
      segmentIndex: 0,
      blob: new Blob(["a"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      reason: "manual",
      capturedAt: Date.now(),
      durationMs: 1000,
      contractSnapshot: snapshot
    });
    await markSegmentUploaded({
      flowId: "flow-1",
      stepId: "step-1",
      sessionId: "sess-A",
      segmentIndex: 0,
      uploadedFileId: "file-uploaded"
    });

    await purgeSession({ intric, flowId: "flow-1", stepId: "step-1", sessionId: "sess-A" });

    expect(deleteSpy).toHaveBeenCalledWith({ fileId: "file-uploaded" });
    const remaining = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(remaining).toEqual([]);
  });

  it("swallows server delete errors and still drops the IDB entry", async () => {
    const intric = {
      files: {
        delete: vi.fn(async () => {
          throw new Error("boom");
        })
      }
    } as unknown as Intric;
    await persistRecordingSegment({
      flowId: "flow-1",
      stepId: "step-1",
      sessionId: "sess-A",
      segmentIndex: 0,
      blob: new Blob(["a"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      reason: "manual",
      capturedAt: Date.now(),
      durationMs: 1000,
      contractSnapshot: snapshot
    });
    await markSegmentUploaded({
      flowId: "flow-1",
      stepId: "step-1",
      sessionId: "sess-A",
      segmentIndex: 0,
      uploadedFileId: "file-uploaded"
    });
    await purgeSession({ intric, flowId: "flow-1", stepId: "step-1", sessionId: "sess-A" });
    const remaining = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(remaining).toEqual([]);
  });
});

describe("purgeAllSessions", () => {
  it("deletes every session entry without touching server-side files", async () => {
    await persistRecordingSegment({
      flowId: "flow-1",
      stepId: "step-A",
      sessionId: "sess-1",
      segmentIndex: 0,
      blob: new Blob(["a"]),
      mimeType: "audio/webm",
      reason: "manual",
      capturedAt: Date.now(),
      durationMs: 1000,
      contractSnapshot: snapshot
    });
    await persistRecordingSegment({
      flowId: "flow-1",
      stepId: "step-B",
      sessionId: "sess-2",
      segmentIndex: 0,
      blob: new Blob(["b"]),
      mimeType: "audio/webm",
      reason: "manual",
      capturedAt: Date.now(),
      durationMs: 1000,
      contractSnapshot: snapshot
    });
    await purgeAllSessions({
      flowId: "flow-1",
      sessionIdsByStepId: { "step-A": "sess-1", "step-B": "sess-2" }
    });
    const remaining = [
      ...(await recordingSessionStore.readSession("flow-1", "step-A", "sess-1")),
      ...(await recordingSessionStore.readSession("flow-1", "step-B", "sess-2"))
    ];
    expect(remaining).toEqual([]);
  });
});
