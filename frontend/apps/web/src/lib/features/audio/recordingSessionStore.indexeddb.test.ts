// Regression test for the IndexedDB path. The default
// `recordingSessionStore.test.ts` runs against the in-memory fallback because
// vitest's node environment has no IndexedDB. That mode hid a real IDB-side
// bug — runTransaction returning the IDBRequest object instead of its
// .result, so verifyRoundTrip always failed and the store flipped to memory
// on every write — until it shipped to production. This file boots
// fake-indexeddb (which uses the native structuredClone, so real Blob
// preservation works under node) and a minimal `window` polyfill so the
// store's `isBrowser()` check passes.

import "fake-indexeddb/auto";

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

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

async function clearDb(): Promise<void> {
  await new Promise<void>((resolve) => {
    const req = indexedDB.deleteDatabase("eneo-recording-sessions");
    req.onsuccess = () => resolve();
    req.onerror = () => resolve();
    req.onblocked = () => resolve();
  });
}

beforeAll(() => {
  // The store guards with `typeof window !== "undefined"` so that node-side
  // tools (Vitest collect, SSR) never touch IndexedDB. fake-indexeddb only
  // installs the IDB globals; we polyfill the window shim here.
  if (typeof (globalThis as { window?: unknown }).window === "undefined") {
    (globalThis as { window: typeof globalThis }).window = globalThis;
  }
});

beforeEach(async () => {
  recordingSessionStore.__resetForTests();
  await clearDb();
});

afterEach(async () => {
  recordingSessionStore.__resetForTests();
  await clearDb();
});

describe("recordingSessionStore — fake-indexeddb path", () => {
  it("writeSegment reports mode=indexeddb when the round-trip check passes", async () => {
    const result = await recordingSessionStore.writeSegment(makeRecord());
    expect(result).toEqual({ persisted: true, mode: "indexeddb" });
  });

  it("does not regress to memory between writes once a round-trip has succeeded", async () => {
    const first = await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 0 }));
    const second = await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 1 }));
    expect(first.mode).toBe("indexeddb");
    expect(second.mode).toBe("indexeddb");
  });

  it("readSession returns the persisted segment with its blob bytes intact", async () => {
    await recordingSessionStore.writeSegment(
      makeRecord({ segmentIndex: 0, blob: new Blob(["abcd"], { type: "audio/webm" }) })
    );
    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records).toHaveLength(1);
    expect(records[0]?.blob).toBeInstanceOf(Blob);
    expect(records[0]?.blob.size).toBe(4);
  });

  it("keeps no copy in memory of a segment IndexedDB holds", async () => {
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 0 }));
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 1 }));

    // A five-hour recording is fifteen parts; memory holds only what storage could not.
    expect(recordingSessionStore.__unpersistedCountForTests()).toBe(0);
  });

  it("keeps earlier stored parts readable, recoverable and deletable after a later write fails", async () => {
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 0 }));
    const put = vi.spyOn(IDBObjectStore.prototype, "put").mockImplementationOnce(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    const failed = await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 1 }));
    put.mockRestore();

    expect(failed).toEqual({ persisted: false, mode: "memory" });
    expect(recordingSessionStore.__unpersistedCountForTests()).toBe(1);
    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records.map((r) => r.segmentIndex)).toEqual([0, 1]);
    const [hint] = await recordingSessionStore.listRecoverableSessions("flow-1", "step-1");
    expect(hint?.segmentCount).toBe(2);

    await recordingSessionStore.patchUploadedFileId("flow-1", "step-1", "sess-A", 0, "file-0");
    const patched = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(patched[0]?.uploadedFileId).toBe("file-0");

    await recordingSessionStore.deleteSession("flow-1", "step-1", "sess-A");
    expect(await recordingSessionStore.readSession("flow-1", "step-1", "sess-A")).toEqual([]);
  });

  it("refuses a read IndexedDB could not finish, so no part of a recording passes for all of it", async () => {
    const old = Date.now() - 48 * 60 * 60 * 1000;
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 0, capturedAt: old }));
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 1 }));
    const cursor = vi.spyOn(IDBObjectStore.prototype, "openCursor").mockImplementation(() => {
      throw new DOMException("read failed", "UnknownError");
    });
    await expect(recordingSessionStore.readSession("flow-1", "step-1", "sess-A")).rejects.toThrow();
    await expect(
      recordingSessionStore.listRecoverableSessions("flow-1", "step-1")
    ).rejects.toThrow();
    cursor.mockRestore();

    // Nothing was expired or lost on the way: both parts are still there.
    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records.map((r) => r.segmentIndex)).toEqual([0, 1]);
  });

  it("tries IndexedDB again after it failed to open, instead of keeping every later part in memory", async () => {
    recordingSessionStore.__resetForTests();
    const open = vi.spyOn(indexedDB, "open").mockImplementationOnce(() => {
      throw new DOMException("open failed", "UnknownError");
    });
    expect(await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 0 }))).toEqual({
      persisted: false,
      mode: "memory"
    });
    open.mockRestore();

    expect(await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 1 }))).toEqual({
      persisted: true,
      mode: "indexeddb"
    });
    expect(recordingSessionStore.__unpersistedCountForTests()).toBe(1);
    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records.map((r) => r.segmentIndex)).toEqual([0, 1]);
  });

  it("reads what memory holds while IndexedDB does not open at all (a private window)", async () => {
    recordingSessionStore.__resetForTests();
    const open = vi.spyOn(indexedDB, "open").mockImplementation(() => {
      throw new DOMException("open failed", "InvalidStateError");
    });
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 0 }));
    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    const [hint] = await recordingSessionStore.listRecoverableSessions("flow-1", "step-1");
    open.mockRestore();

    expect(records.map((r) => r.segmentIndex)).toEqual([0]);
    expect(hint?.segmentCount).toBe(1);
  });

  it("keeps the whole session, stored and memory parts, when IndexedDB cannot delete it", async () => {
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 0 }));
    const put = vi.spyOn(IDBObjectStore.prototype, "put").mockImplementationOnce(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 1 }));
    put.mockRestore();
    const remove = vi.spyOn(IDBObjectStore.prototype, "delete").mockImplementationOnce(() => {
      throw new DOMException("delete failed", "UnknownError");
    });

    await expect(
      recordingSessionStore.deleteSession("flow-1", "step-1", "sess-A")
    ).rejects.toThrow();
    remove.mockRestore();

    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records.map((r) => r.segmentIndex)).toEqual([0, 1]);
  });

  it("patchUploadedFileId mutates only the targeted segment via IDB", async () => {
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 0 }));
    await recordingSessionStore.writeSegment(makeRecord({ segmentIndex: 1 }));
    await recordingSessionStore.patchUploadedFileId("flow-1", "step-1", "sess-A", 0, "uploaded-id");
    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records[0]?.uploadedFileId).toBe("uploaded-id");
    expect(records[1]?.uploadedFileId).toBeNull();
  });
});
