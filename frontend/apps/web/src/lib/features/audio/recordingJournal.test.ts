import { describe, expect, it, vi } from "vitest";
import { journalLockName, JOURNAL_MAX_PENDING_CHUNKS, RecordingJournal } from "./recordingJournal";
import { fakeLocks } from "./recordingJournalTestLocks";
import type { ContractSnapshot } from "./recordingSessionStore";

const snapshot: ContractSnapshot = {
  publishedFlowVersion: 1,
  maxFiles: 10,
  maxFileSizeBytes: null,
  acceptedMimetypes: [],
  inputFormat: "audio"
};

const meta = {
  flowId: "flow-1",
  stepId: "step-1",
  sessionId: "sess-A",
  mimeType: "audio/webm",
  startedAt: 1,
  contractSnapshot: snapshot
};

function fakeStore() {
  const written: [string, number, string][] = [];
  const writtenAt: number[] = [];
  const dropped: string[] = [];
  let hold: Promise<void> | null = null;
  return {
    written,
    writtenAt,
    dropped,
    holdWrites(promise: Promise<void>) {
      hold = promise;
    },
    beginJournalPart: vi.fn(async (part: { partId: string }) => `key-${part.partId}`),
    appendJournalChunk: vi.fn(async (key: string, seq: number, blob: Blob, at: number) => {
      if (hold) await hold;
      written.push([key, seq, await blob.text()]);
      writtenAt.push(at);
    }),
    dropJournalPart: vi.fn(async (key: string) => {
      dropped.push(key);
    })
  };
}

describe("RecordingJournal", () => {
  it("writes a part's chunks in order and drops the part once it is committed", async () => {
    const store = fakeStore();
    const journal = new RecordingJournal(store, vi.fn(), fakeLocks());

    journal.begin("p1", meta);
    journal.append("p1", new Blob(["a"]));
    journal.append("p1", new Blob(["b"]));
    await journal.commit("p1");

    expect(store.written).toEqual([
      ["key-p1", 0, "a"],
      ["key-p1", 1, "b"]
    ]);
    expect(store.dropped).toEqual(["key-p1"]);
  });

  it("says so, and keeps what it wrote, when storage falls behind or fails", async () => {
    const store = fakeStore();
    const degraded = vi.fn();
    const journal = new RecordingJournal(store, degraded, fakeLocks());
    let release = () => {};
    store.holdWrites(new Promise<void>((resolve) => (release = resolve)));

    journal.begin("p1", meta);
    for (let chunk = 0; chunk <= JOURNAL_MAX_PENDING_CHUNKS; chunk += 1) {
      journal.append("p1", new Blob([String(chunk)]));
    }
    expect(degraded).toHaveBeenCalledExactlyOnceWith("failed");
    release();
    await journal.commit("p1");
    // The chunks queued before it fell behind are written; none after.
    expect(store.written).toHaveLength(JOURNAL_MAX_PENDING_CHUNKS);
  });

  it("holds a lock for the part while it records, so another tab does not take it over", async () => {
    const locks = fakeLocks();
    const journal = new RecordingJournal(fakeStore(), vi.fn(), locks);

    journal.begin("p1", meta);
    expect([...locks.held.keys()]).toEqual([journalLockName("p1")]);
    await journal.commit("p1");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(locks.held.size).toBe(0);
  });

  it("leaves a part the recorder went away from in the journal, and lets its lock go", async () => {
    const store = fakeStore();
    const locks = fakeLocks();
    const journal = new RecordingJournal(store, vi.fn(), locks);

    journal.begin("p1", meta);
    journal.append("p1", new Blob(["a"]));
    await journal.leave("p1");
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(store.written).toEqual([["key-p1", 0, "a"]]);
    expect(store.dropped).toEqual([]);
    expect(locks.held.size).toBe(0);
  });

  it("keeps the part's lock until its journal is dropped", async () => {
    const store = fakeStore();
    const locks = fakeLocks();
    const lockedAtDrop: boolean[] = [];
    store.dropJournalPart.mockImplementation(async () => {
      lockedAtDrop.push(locks.held.has(journalLockName("p1")));
    });
    const journal = new RecordingJournal(store, vi.fn(), locks);

    journal.begin("p1", meta);
    await journal.commit("p1");
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(lockedAtDrop).toEqual([true]);
    expect(locks.held.size).toBe(0);
  });

  it("lets go of a lock granted only after the part ended", async () => {
    const store = fakeStore();
    let grant = () => Promise.resolve();
    const locks = {
      request: vi.fn((_name: string, callback: () => Promise<void>) => {
        grant = callback;
        return new Promise(() => undefined);
      })
    } as unknown as LockManager;
    const journal = new RecordingJournal(store, vi.fn(), locks);

    journal.begin("p1", meta);
    await journal.leave("p1");

    await expect(grant()).resolves.toBeUndefined();
  });

  it("writes nothing of a part until its lock is granted", async () => {
    const store = fakeStore();
    let grant = () => Promise.resolve();
    const locks = {
      request: vi.fn((_name: string, callback: () => Promise<void>) => {
        grant = callback;
        return new Promise(() => undefined);
      })
    } as unknown as LockManager;
    const journal = new RecordingJournal(store, vi.fn(), locks);

    journal.begin("p1", meta);
    journal.append("p1", new Blob(["a"]));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(store.beginJournalPart).not.toHaveBeenCalled();

    void grant();
    await journal.leave("p1");
    expect(store.written).toEqual([["key-p1", 0, "a"]]);
  });

  it("writes the chunks of a part left before its lock was granted, once it is", async () => {
    const store = fakeStore();
    let grant = () => Promise.resolve();
    const locks = {
      request: vi.fn((_name: string, callback: () => Promise<void>) => {
        grant = callback;
        return new Promise(() => undefined);
      })
    } as unknown as LockManager;
    const journal = new RecordingJournal(store, vi.fn(), locks);

    journal.begin("p1", meta);
    journal.append("p1", new Blob(["a"]));
    const left = journal.leave("p1");
    void grant();
    await left;

    expect(store.written).toEqual([["key-p1", 0, "a"]]);
    expect(store.dropped).toEqual([]);
  });

  it("keeps when each chunk was recorded, not when storage got to it", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(10_000);
    const store = fakeStore();
    let release = () => {};
    store.holdWrites(new Promise<void>((resolve) => (release = resolve)));
    const journal = new RecordingJournal(store, vi.fn(), fakeLocks());

    journal.begin("p1", meta);
    journal.append("p1", new Blob(["a"]));
    vi.setSystemTime(40_000);
    release();
    await journal.commit("p1");
    vi.useRealTimers();

    expect(store.writtenAt).toEqual([10_000]);
  });

  it("says so, and writes nothing more, when the part's lock is refused", async () => {
    const store = fakeStore();
    const degraded = vi.fn();
    const locks = { request: vi.fn(async () => Promise.reject(new Error("no"))) };
    const journal = new RecordingJournal(store, degraded, locks as unknown as LockManager);

    journal.begin("p1", meta);
    await new Promise((resolve) => setTimeout(resolve, 0));
    journal.append("p1", new Blob(["a"]));
    await journal.commit("p1");

    expect(degraded).toHaveBeenCalledExactlyOnceWith("failed");
    expect(store.beginJournalPart).not.toHaveBeenCalled();
    expect(store.written).toEqual([]);
  });

  it("journals nothing, and says so, without Web Locks or for audio whose cut-off end is not known to play", async () => {
    const store = fakeStore();
    const degraded = vi.fn();
    new RecordingJournal(store, degraded, null).begin("p1", meta);
    new RecordingJournal(store, degraded, fakeLocks()).begin("p2", {
      ...meta,
      mimeType: "audio/mp4"
    });

    expect(store.beginJournalPart).not.toHaveBeenCalled();
    expect(degraded.mock.calls).toEqual([["unavailable"], ["unavailable"]]);
  });
});
