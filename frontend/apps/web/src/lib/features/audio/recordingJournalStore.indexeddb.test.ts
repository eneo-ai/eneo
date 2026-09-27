// The journal a running recording writes as it goes: part metadata and chunks,
// in separate object stores so a scan never reads audio.

import "fake-indexeddb/auto";

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { recoverInterruptedParts } from "./flowRunRecordingSession";
import { journalLockName } from "./recordingJournal";
import { fakeLocks } from "./recordingJournalTestLocks";
import {
  recordingSessionStore,
  SESSION_RECOVERY_TTL_MS,
  type ContractSnapshot
} from "./recordingSessionStore";

const snapshot: ContractSnapshot = {
  publishedFlowVersion: 1,
  maxFiles: 10,
  maxFileSizeBytes: 25_000_000,
  acceptedMimetypes: ["audio/webm"],
  inputFormat: "audio"
};

const part = {
  flowId: "flow-1",
  stepId: "step-1",
  sessionId: "sess-A",
  partId: "part-1",
  mimeType: "audio/webm",
  startedAt: 1_000,
  contractSnapshot: snapshot
};

// In a browser (the tests' `window`) a part always gets its key.
const begin = async (meta: typeof part) => (await recordingSessionStore.beginJournalPart(meta))!;

async function clearDb(): Promise<void> {
  await new Promise<void>((resolve) => {
    const req = indexedDB.deleteDatabase("eneo-recording-sessions");
    req.onsuccess = () => resolve();
    req.onerror = () => resolve();
    req.onblocked = () => resolve();
  });
}

beforeAll(() => {
  if (typeof (globalThis as { window?: unknown }).window === "undefined") {
    (globalThis as { window: typeof globalThis }).window = globalThis;
  }
});

beforeEach(async () => {
  recordingSessionStore.__resetForTests();
  await clearDb();
});

afterEach(() => {
  recordingSessionStore.__resetForTests();
  vi.restoreAllMocks();
});

describe("recording journal", () => {
  it("keeps a part's chunks in order, lists the part without its audio, and drops it whole", async () => {
    const key = await begin(part);
    for (const [seq, text] of ["a", "b", "c"].entries()) {
      await recordingSessionStore.appendJournalChunk(key, seq, new Blob([text]), 2_000 + seq);
    }

    const [listed] = await recordingSessionStore.listJournalParts("flow-1", "step-1");
    expect(listed).toMatchObject({ key, sessionId: "sess-A", chunkCount: 3, lastChunkAt: 2_002 });
    const chunks = (await recordingSessionStore.readJournalChunks(key)) ?? [];
    expect(await new Blob(chunks.map((chunk) => chunk.blob)).text()).toBe("abc");
    expect(chunks.map((chunk) => chunk.at)).toEqual([2_000, 2_001, 2_002]);

    await recordingSessionStore.dropJournalPart(key);
    expect(await recordingSessionStore.listJournalParts("flow-1", "step-1")).toEqual([]);
    expect(await recordingSessionStore.readJournalChunks(key)).toEqual([]);
  });

  it("lists only the parts of the asked flow and step", async () => {
    await recordingSessionStore.beginJournalPart(part);
    await recordingSessionStore.beginJournalPart({ ...part, stepId: "step-2", partId: "part-2" });
    const listed = await recordingSessionStore.listJournalParts("flow-1", "step-1");
    expect(listed.map((meta) => meta.partId)).toEqual(["part-1"]);
  });

  it("opens a store the earlier version made, and keeps its saved parts", async () => {
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open("eneo-recording-sessions", 1);
      request.onupgradeneeded = () => {
        const store = request.result.createObjectStore("segments", { keyPath: "compositeKey" });
        store.put({
          compositeKey: "flow-1::step-1::sess-A::0000",
          flowId: "flow-1",
          stepId: "step-1",
          sessionId: "sess-A",
          segmentIndex: 0,
          blob: new Blob(["old"]),
          mimeType: "audio/webm",
          durationMs: 1_000,
          capturedAt: Date.now(),
          uploadedFileId: null,
          reason: "manual",
          contractSnapshot: snapshot
        });
      };
      request.onsuccess = () => {
        request.result.close();
        resolve();
      };
      request.onerror = () => reject(request.error);
    });

    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records.map((record) => record.segmentIndex)).toEqual([0]);
    await recordingSessionStore.beginJournalPart(part);
    expect(await recordingSessionStore.listJournalParts("flow-1", "step-1")).toHaveLength(1);
  });

  async function journal(meta = part, texts = ["a", "b"]): Promise<string> {
    const key = await begin(meta);
    for (const [seq, text] of texts.entries()) {
      await recordingSessionStore.appendJournalChunk(key, seq, new Blob([text]), 5_000 + seq);
    }
    return key;
  }

  const now = 10_000;

  it("rebuilds an interrupted part as the recording's next part, and drops its journal", async () => {
    await recordingSessionStore.writeSegment({
      flowId: "flow-1",
      stepId: "step-1",
      sessionId: "sess-A",
      segmentIndex: 0,
      blob: new Blob(["x"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: 900,
      uploadedFileId: "file-0",
      reason: "rotation",
      contractSnapshot: snapshot
    });
    await journal();

    await recoverInterruptedParts("flow-1", "step-1", fakeLocks(), now);

    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records[1]).toMatchObject({
      segmentIndex: 1,
      mimeType: "audio/webm",
      durationMs: 4_001,
      capturedAt: 5_001,
      uploadedFileId: null,
      reason: "interrupted",
      partId: "part-1"
    });
    expect(await records[1]!.blob.text()).toBe("ab");
    const { hints } = await recordingSessionStore.listRecoverableSessions("flow-1", "step-1", now);
    expect(hints[0]).toMatchObject({ segmentCount: 2, interruptedAt: 5_001 });
    expect(await recordingSessionStore.listJournalParts("flow-1", "step-1")).toEqual([]);
  });

  it("rebuilds interrupted parts in the order they were recorded", async () => {
    await journal({ ...part, partId: "later", startedAt: 3_000 }, ["2"]);
    await journal({ ...part, partId: "earlier", startedAt: 2_000 }, ["1"]);

    await recoverInterruptedParts("flow-1", "step-1", fakeLocks(), now);

    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records.map((record) => record.partId)).toEqual(["earlier", "later"]);
    // The recording began when its first part did, not when that part was saved.
    const { hints } = await recordingSessionStore.listRecoverableSessions("flow-1", "step-1", now);
    expect(hints[0]?.startedAt).toBe(2_000);
  });

  it("only drops the journal of a part that is already stored, or holds no audio", async () => {
    await recordingSessionStore.writeSegment({
      flowId: "flow-1",
      stepId: "step-1",
      sessionId: "sess-A",
      segmentIndex: 0,
      blob: new Blob(["whole"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: 900,
      uploadedFileId: null,
      reason: "manual",
      contractSnapshot: snapshot,
      partId: "part-1"
    });
    await journal();
    await journal({ ...part, partId: "empty" }, []);

    await recoverInterruptedParts("flow-1", "step-1", fakeLocks(), now);

    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records.map((record) => record.partId)).toEqual(["part-1"]);
    expect(await recordingSessionStore.listJournalParts("flow-1", "step-1")).toEqual([]);
  });

  it("leaves a part another tab is still recording", async () => {
    await journal();
    const locks = fakeLocks();
    let stopRecording = () => {};
    void locks.request(
      journalLockName("part-1"),
      () => new Promise<void>((r) => (stopRecording = r))
    );

    expect(await recoverInterruptedParts("flow-1", "step-1", locks, now)).toBe(true);

    expect(await recordingSessionStore.readSession("flow-1", "step-1", "sess-A")).toEqual([]);
    expect(await recordingSessionStore.listJournalParts("flow-1", "step-1")).toHaveLength(1);
    stopRecording();
  });

  it("recovers nothing without Web Locks, where it cannot tell a part from one still recording", async () => {
    await journal();

    expect(await recoverInterruptedParts("flow-1", "step-1", null, now)).toBe(true);

    expect(await recordingSessionStore.listJournalParts("flow-1", "step-1")).toHaveLength(1);
  });

  it("gives parts two tabs recover into one recording each their own place", async () => {
    await journal({ ...part, partId: "first", startedAt: 1_000 }, ["1"]);
    await journal({ ...part, partId: "second", startedAt: 2_000 }, ["2"]);
    const locks = fakeLocks();
    // The other tab sees only the second part: its scan started before the first was listed.
    const list = recordingSessionStore.listJournalParts.bind(recordingSessionStore);
    const spy = vi
      .spyOn(recordingSessionStore, "listJournalParts")
      .mockImplementationOnce(async (...args) =>
        (await list(...args)).filter((p) => p.partId === "second")
      );

    await Promise.all([
      recoverInterruptedParts("flow-1", "step-1", locks, now),
      recoverInterruptedParts("flow-1", "step-1", locks, now)
    ]);
    spy.mockRestore();

    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records.map((r) => [r.segmentIndex, r.partId])).toEqual([
      [0, "second"],
      [1, "first"]
    ]);
  });

  it("rebuilds a part whose stored copy does not read back, in its place, and keeps the journal until it does", async () => {
    await recordingSessionStore.writeSegment({
      flowId: "flow-1",
      stepId: "step-1",
      sessionId: "sess-A",
      segmentIndex: 0,
      blob: new Blob(["whole"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: 900,
      uploadedFileId: null,
      reason: "manual",
      contractSnapshot: snapshot,
      partId: "part-1"
    });
    await journal();
    const read = vi.spyOn(Blob.prototype, "arrayBuffer");
    const plays = async () => new ArrayBuffer(1);
    // Reads in order: the stored copy, the journal's two chunks, the rebuilt copy.
    // The stored copy and then the rebuilt one fail to read back: the journal stays.
    read
      .mockRejectedValueOnce(new Error("gone"))
      .mockImplementationOnce(plays)
      .mockImplementationOnce(plays)
      .mockRejectedValueOnce(new Error("gone"));

    expect(await recoverInterruptedParts("flow-1", "step-1", fakeLocks(), now)).toBe(false);
    expect(await recordingSessionStore.listJournalParts("flow-1", "step-1")).toHaveLength(1);

    read.mockRejectedValueOnce(new Error("gone"));
    expect(await recoverInterruptedParts("flow-1", "step-1", fakeLocks(), now)).toBe(true);
    read.mockRestore();

    const records = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(records.map((r) => [r.segmentIndex, r.partId])).toEqual([[0, "part-1"]]);
    expect(await records[0]!.blob.text()).toBe("ab");
    expect(await recordingSessionStore.listJournalParts("flow-1", "step-1")).toEqual([]);
  });

  it("rebuilds only the chunks that follow on from the start", async () => {
    const key = await journal(part, ["a", "b"]);
    await recordingSessionStore.appendJournalChunk(key, 3, new Blob(["d"]), 6_000);

    const chunks = (await recordingSessionStore.readJournalChunks(key)) ?? [];
    expect(await new Blob(chunks.map((chunk) => chunk.blob)).text()).toBe("ab");
  });

  it("rebuilds a part only up to its first chunk that does not read back, and ends it there", async () => {
    await journal(part, ["a", "b", "c"]);
    // The first chunk reads back; the second does not.
    vi.spyOn(Blob.prototype, "arrayBuffer")
      .mockImplementationOnce(async () => new ArrayBuffer(1))
      .mockRejectedValueOnce(new Error("gone"));

    await recoverInterruptedParts("flow-1", "step-1", fakeLocks(), now);

    const [record] = await recordingSessionStore.readSession("flow-1", "step-1", "sess-A");
    expect(await record!.blob.text()).toBe("a");
    expect(record).toMatchObject({ capturedAt: 5_000, durationMs: 4_000 });
  });

  it("keeps the journal, and says the scan is incomplete, when a chunk is only slow to read", async () => {
    await journal(part, ["a", "b"]);
    vi.spyOn(Blob.prototype, "arrayBuffer")
      .mockImplementationOnce(async () => new ArrayBuffer(1))
      .mockImplementationOnce(() => new Promise<ArrayBuffer>(() => undefined));

    expect(await recoverInterruptedParts("flow-1", "step-1", fakeLocks(), now)).toBe(false);

    expect(await recordingSessionStore.readSession("flow-1", "step-1", "sess-A")).toEqual([]);
    expect(await recordingSessionStore.listJournalParts("flow-1", "step-1")).toHaveLength(1);
  });

  it("refuses a chunk that does not read back", async () => {
    const key = await begin(part);
    vi.spyOn(Blob.prototype, "arrayBuffer").mockRejectedValueOnce(new Error("gone"));

    await expect(
      recordingSessionStore.appendJournalChunk(key, 0, new Blob(["a"]), 2_000)
    ).rejects.toThrow();
  });

  it("drops a journal older than a saved recording is kept", async () => {
    await journal();

    await recoverInterruptedParts(
      "flow-1",
      "step-1",
      fakeLocks(),
      5_001 + SESSION_RECOVERY_TTL_MS + 1
    );

    expect(await recordingSessionStore.readSession("flow-1", "step-1", "sess-A")).toEqual([]);
    expect(await recordingSessionStore.listJournalParts("flow-1", "step-1")).toEqual([]);
  });

  it("deletes a recording's journal with the recording", async () => {
    const key = await journal();
    await journal({ ...part, sessionId: "sess-B", partId: "part-2" });

    await recordingSessionStore.deleteSession("flow-1", "step-1", "sess-A");

    const left = await recordingSessionStore.listJournalParts("flow-1", "step-1");
    expect(left.map((meta) => meta.partId)).toEqual(["part-2"]);
    expect(await recordingSessionStore.readJournalChunks(key)).toEqual([]);
  });
});
