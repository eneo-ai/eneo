// Integration test for the IndexedDB-backed segment ledger. Vitest's
// default jsdom environment doesn't ship with IndexedDB, so the store
// drops to its in-memory fallback — which is the path we most need to
// exercise: it must round-trip writes, expire stale segments, and let
// the dialog list resumable sessions per (flowId, stepId).

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  recordingSessionStore,
  SESSION_RECOVERY_TTL_MS,
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
    sessionId: "sess-A",
    segmentIndex: 0,
    blob: new Blob(["a"], { type: "audio/webm" }),
    mimeType: "audio/webm",
    durationMs: 1000,
    capturedAt: Date.now(),
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

describe("recordingSessionStore", () => {
  it("round-trips a written segment via readSession", async () => {
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 0 }));
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 1 }));
    const result = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(result.map((r) => r.segmentIndex)).toEqual([0, 1]);
  });

  it("patchUploadedFileId mutates only the targeted segment", async () => {
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 0 }));
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 1 }));
    await recordingSessionStore.patchUploadedFileId("flow-1", "step-1", "sess-A", 0, "uploaded-id");
    const result = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(result[0]?.uploadedFileId).toBe("uploaded-id");
    expect(result[1]?.uploadedFileId).toBeNull();
  });

  it("listRecoverableSessions groups segments by sessionId for the given (flow, step)", async () => {
    await recordingSessionStore.writeSegment(makeRecord({ sessionId: "sess-A", segmentIndex: 0 }));
    await recordingSessionStore.writeSegment(makeRecord({ sessionId: "sess-A", segmentIndex: 1 }));
    await recordingSessionStore.writeSegment(makeRecord({ sessionId: "sess-B", segmentIndex: 0 }));
    const hints = await recordingSessionStore.listRecoverableSessions("flow-1", "step-1");
    const bySession = new Map(hints.map((h) => [h.sessionId, h]));
    expect(bySession.get("sess-A")?.segmentCount).toBe(2);
    expect(bySession.get("sess-B")?.segmentCount).toBe(1);
  });

  it("listRecoverableSessions skips sessions older than the 24-hour TTL", async () => {
    const now = Date.now();
    await recordingSessionStore.writeSegment(
      makeRecord({
        sessionId: "expired",
        capturedAt: now - SESSION_RECOVERY_TTL_MS - 1_000
      })
    );
    await recordingSessionStore.writeSegment(
      makeRecord({ sessionId: "fresh", capturedAt: now - 1_000 })
    );
    const hints = await recordingSessionStore.listRecoverableSessions("flow-1", "step-1", now);
    expect(hints.map((h) => h.sessionId)).toEqual(["fresh"]);
  });

  it("deleteSession removes every segment of the given session", async () => {
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 0 }));
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 1 }));
    await recordingSessionStore.deleteSession("flow-1", "step-1", "sess-A");
    const result = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(result).toEqual([]);
  });
});
