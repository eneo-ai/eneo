// IndexedDB-backed segment ledger. Memory holds only the parts IndexedDB could not
// store (a failed write or Blob round trip), and every read combines the two.

import type { RecordingStopReason } from "./recordedAudioFile";
import { withRecordedDuration } from "./webmDuration";

const DB_NAME = "eneo-recording-sessions";
// Version 2 adds the journal a running recording writes as it goes.
const DB_VERSION = 2;
const STORE_NAME = "segments";
const JOURNAL_PARTS = "journalParts";
const JOURNAL_CHUNKS = "journalChunks";
const SESSION_TTL_MS = 24 * 60 * 60 * 1000;
const ROUND_TRIP_VERIFY_TIMEOUT_MS = 2_000;

export type SegmentRecord = {
  flowId: string;
  stepId: string;
  sessionId: string;
  segmentIndex: number;
  blob: Blob;
  mimeType: string;
  durationMs: number;
  capturedAt: number;
  uploadedFileId: string | null;
  reason: RecordingStopReason;
  contractSnapshot: ContractSnapshot;
  // The journal part it was recorded as: recovery never rebuilds a part that is stored.
  partId?: string;
};

export type ContractSnapshot = {
  publishedFlowVersion: number | null;
  maxFiles: number | null;
  maxFileSizeBytes: number | null;
  acceptedMimetypes: string[];
  inputFormat: string | null;
};

export type SessionRecoveryHint = {
  flowId: string;
  stepId: string;
  sessionId: string;
  segmentCount: number;
  totalDurationMs: number;
  // When the recording began: its first part's save time less that part's length.
  startedAt: number;
  uploadedCount: number;
  // When the audio of a part rebuilt from the journal ends (the page closed while
  // it recorded), or null.
  interruptedAt: number | null;
  contractSnapshot: ContractSnapshot;
};

export type StoreMode = "indexeddb" | "memory";

// A part being recorded: what the journal knows without reading its audio.
export type JournalPart = {
  key: string;
  flowId: string;
  stepId: string;
  sessionId: string;
  partId: string;
  mimeType: string;
  startedAt: number;
  lastChunkAt: number;
  chunkCount: number;
  contractSnapshot: ContractSnapshot;
};

// Size and first byte: reading one byte makes the engine open the stored bytes, so a
// Blob that only referenced a temporary file the tab lost fails here, not at upload.
async function readsBack(blob: Blob): Promise<boolean> {
  if (blob.size === 0) return true;
  try {
    return (await blob.slice(0, 1).arrayBuffer()).byteLength > 0;
  } catch {
    return false;
  }
}

// The whole check, the read of the record and of its bytes, has one time bound.
// Null when it had no answer by then: slow is not the same as gone.
function withinVerifyTime(check: Promise<boolean>): Promise<boolean | null> {
  return Promise.race([
    check.catch(() => false),
    new Promise<null>((resolve) => setTimeout(() => resolve(null), ROUND_TRIP_VERIFY_TIMEOUT_MS))
  ]);
}

class RecordingSessionStoreImpl {
  private db: IDBDatabase | null = null;
  // Parts IndexedDB could not store, by composite key; nothing that it holds.
  private memoryFallback = new Map<string, SegmentRecord>();
  private openPromise: Promise<IDBDatabase | null> | null = null;

  private isBrowser(): boolean {
    return typeof indexedDB !== "undefined" && typeof window !== "undefined";
  }

  private compositeKey(
    flowId: string,
    stepId: string,
    sessionId: string,
    segmentIndex: number
  ): string {
    return `${flowId}::${stepId}::${sessionId}::${segmentIndex.toString().padStart(4, "0")}`;
  }

  private sessionPrefix(flowId: string, stepId: string, sessionId: string): string {
    return `${flowId}::${stepId}::${sessionId}::`;
  }

  private async openDb(): Promise<IDBDatabase | null> {
    if (!this.isBrowser()) return null;
    if (this.db) return this.db;
    if (this.openPromise) return this.openPromise;

    const opening = new Promise<IDBDatabase | null>((resolve) => {
      try {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = () => {
          const db = request.result;
          if (!db.objectStoreNames.contains(STORE_NAME)) {
            const store = db.createObjectStore(STORE_NAME, { keyPath: "compositeKey" });
            store.createIndex("by_session", ["flowId", "stepId", "sessionId"]);
            store.createIndex("by_capturedAt", "capturedAt");
          }
          // The earlier version's saved parts stay as they are.
          if (!db.objectStoreNames.contains(JOURNAL_PARTS)) {
            db.createObjectStore(JOURNAL_PARTS, { keyPath: "key" });
          }
          if (!db.objectStoreNames.contains(JOURNAL_CHUNKS)) {
            db.createObjectStore(JOURNAL_CHUNKS, { keyPath: "key" });
          }
        };
        request.onsuccess = () => {
          // A blocked attempt can still open after a later one did: keep one connection.
          if (this.db) request.result.close();
          else {
            const db = request.result;
            this.db = db;
            // Another tab opening a newer version: let it, and open again when needed.
            db.onversionchange = () => {
              db.close();
              if (this.db === db) this.db = null;
              this.openPromise = null;
            };
          }
          resolve(this.db);
        };
        request.onerror = () => {
          console.warn("RecordingSessionStore: indexedDB.open failed", request.error);
          resolve(null);
        };
        request.onblocked = () => {
          console.warn("RecordingSessionStore: indexedDB.open blocked, using memory");
          resolve(null);
        };
      } catch (error) {
        console.warn("RecordingSessionStore: indexedDB.open threw, using memory", error);
        resolve(null);
      }
    });

    // A failed attempt is not kept: the next write tries IndexedDB again rather than
    // keeping the rest of a long recording in memory.
    this.openPromise = opening;
    void opening.then((db) => {
      if (db === null && this.openPromise === opening) this.openPromise = null;
    });
    return opening;
  }

  // Round-trip-verifying write: some browsers persist a *reference* to the
  // Blob (a temp file) rather than a copy, and that reference can be
  // invalidated when the tab closes. Reading the record back and touching
  // the bytes is the only way to know we actually own the data.
  async writeSegment(record: SegmentRecord): Promise<{ persisted: boolean; mode: StoreMode }> {
    const compositeKey = this.compositeKey(
      record.flowId,
      record.stepId,
      record.sessionId,
      record.segmentIndex
    );
    if ((await this.openDb()) !== null) {
      try {
        await this.runTransaction("readwrite", (store) => {
          store.put({ ...record, compositeKey });
        });
        if (await this.verifyRoundTrip(compositeKey, record.blob.size)) {
          this.memoryFallback.delete(compositeKey);
          return { persisted: true, mode: "indexeddb" };
        }
        console.warn(
          "RecordingSessionStore: Blob round-trip verification failed, keeping it in memory"
        );
      } catch (error) {
        console.warn("RecordingSessionStore: write failed, keeping it in memory", error);
      }
    }
    this.memoryFallback.set(compositeKey, record);
    return { persisted: false, mode: "memory" };
  }

  private verifyRoundTrip(
    compositeKey: string,
    expectedSize: number,
    storeName: string = STORE_NAME
  ): Promise<boolean | null> {
    return withinVerifyTime(
      this.runTransaction<unknown>("readonly", (store) => store.get(compositeKey), storeName).then(
        (record) => {
          const blob = (record as { blob?: unknown } | undefined)?.blob;
          return blob instanceof Blob && blob.size === expectedSize && readsBack(blob);
        }
      )
    );
  }

  async readSession(flowId: string, stepId: string, sessionId: string): Promise<SegmentRecord[]> {
    const { records } = await this.readRange(this.sessionPrefix(flowId, stepId, sessionId));
    return records.sort((a, b) => a.segmentIndex - b.segmentIndex);
  }

  async patchUploadedFileId(
    flowId: string,
    stepId: string,
    sessionId: string,
    segmentIndex: number,
    uploadedFileId: string
  ): Promise<void> {
    const compositeKey = this.compositeKey(flowId, stepId, sessionId, segmentIndex);
    const memoryRecord = this.memoryFallback.get(compositeKey);
    if (memoryRecord) {
      this.memoryFallback.set(compositeKey, { ...memoryRecord, uploadedFileId });
    }

    // Rejects when IndexedDB could not mark it: the part would upload again after a reload.
    if ((await this.openDb()) === null) return;
    await this.runTransaction("readwrite", (store) => {
      return new Promise<void>((resolve, reject) => {
        const get = store.get(compositeKey);
        get.onsuccess = () => {
          const record = get.result as (SegmentRecord & { compositeKey: string }) | undefined;
          if (!record) {
            resolve();
            return;
          }
          try {
            const put = store.put({ ...record, uploadedFileId });
            put.onsuccess = () => resolve();
            put.onerror = () => reject(put.error);
          } catch (error) {
            reject(error);
          }
        };
        get.onerror = () => reject(get.error);
      });
    });
  }

  // Removes one recorded part, named by its session and index (a part whose
  // upload mark failed has no upload ID in the store). Rejects when IndexedDB could
  // not remove it: the part stays, to remove on another try.
  async deleteSegment(
    flowId: string,
    stepId: string,
    sessionId: string,
    segmentIndex: number
  ): Promise<void> {
    const compositeKey = this.compositeKey(flowId, stepId, sessionId, segmentIndex);
    if ((await this.openDb()) !== null) {
      await this.runTransaction("readwrite", (store) => {
        return new Promise<void>((resolve, reject) => {
          const request = store.delete(compositeKey);
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        });
      });
    }
    this.memoryFallback.delete(compositeKey);
  }

  // Rejects when IndexedDB could not delete the stored parts; the parts only memory
  // holds are then kept too, so the whole session stays for another try. The
  // session's journal goes with it.
  async deleteSession(flowId: string, stepId: string, sessionId: string): Promise<void> {
    const prefix = this.sessionPrefix(flowId, stepId, sessionId);
    if ((await this.openDb()) !== null) {
      const range = IDBKeyRange.bound(prefix, prefix + "\uffff");
      await this.runTransaction("readwrite", (store) => {
        return new Promise<void>((resolve, reject) => {
          const request = store.delete(range);
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        });
      });
      await this.runJournal("readwrite", (parts, chunks) => {
        parts.delete(range);
        chunks.delete(range);
      });
    }
    for (const key of Array.from(this.memoryFallback.keys())) {
      if (key.startsWith(prefix)) this.memoryFallback.delete(key);
    }
  }

  async listRecoverableSessions(
    flowId: string,
    stepId: string,
    now: number = Date.now()
  ): Promise<{ hints: SessionRecoveryHint[]; complete: boolean }> {
    const cutoff = now - SESSION_TTL_MS;
    // Without the store only what memory holds is known: offered, and said to be incomplete.
    const { records: segments, stored } = await this.readRange(`${flowId}::${stepId}::`);

    // Group first, then decide expiry per session — never list and delete
    // the same session in one pass, and never expire a multi-hour session
    // because one of its early segments crossed the TTL.
    const bySession = new Map<string, SegmentRecord[]>();
    for (const segment of segments) {
      const list = bySession.get(segment.sessionId);
      if (list) list.push(segment);
      else bySession.set(segment.sessionId, [segment]);
    }

    const hints: SessionRecoveryHint[] = [];
    for (const [sessionId, list] of bySession) {
      list.sort((a, b) => a.segmentIndex - b.segmentIndex);
      const latestCapturedAt = Math.max(...list.map((s) => s.capturedAt));
      // A session is expired if it has had no activity within the TTL
      // window. Using the latest segment as the activity marker means a
      // long recording that's still rotating doesn't get pruned even when
      // its earliest segments are old.
      if (latestCapturedAt < cutoff) {
        void this.deleteSession(flowId, stepId, sessionId).catch((error) =>
          console.warn("RecordingSessionStore: an expired session could not be deleted", error)
        );
        continue;
      }
      const totalDurationMs = list.reduce((sum, s) => sum + (s.durationMs || 0), 0);
      // A part is saved as it ends: the recording began its length earlier.
      const startedAt = Math.min(...list.map((s) => s.capturedAt - (s.durationMs || 0)));
      const uploadedCount = list.filter((s) => s.uploadedFileId !== null).length;
      const interrupted = list.filter((s) => s.reason === "interrupted").map((s) => s.capturedAt);
      hints.push({
        flowId,
        stepId,
        sessionId,
        segmentCount: list.length,
        totalDurationMs,
        startedAt,
        uploadedCount,
        interruptedAt: interrupted.length > 0 ? Math.max(...interrupted) : null,
        contractSnapshot: list[0]?.contractSnapshot ?? {
          publishedFlowVersion: null,
          maxFiles: null,
          maxFileSizeBytes: null,
          acceptedMimetypes: [],
          inputFormat: null
        }
      });
    }

    hints.sort((a, b) => b.startedAt - a.startedAt);
    return { hints, complete: stored };
  }

  // Every part whose composite key starts with `prefix`: the stored ones and the ones
  // only memory holds (memory wins for the same key). A read IndexedDB started but could
  // not finish rejects: stored parts have no copy in memory, so part of a recording must
  // not pass for all of it. When IndexedDB does not open, this tab stored nothing there,
  // and memory holds everything it recorded.
  // `stored` is false when IndexedDB did not open in a browser: only what memory
  // holds is known then (outside a browser memory is the whole ledger).
  private async readRange(prefix: string): Promise<{ records: SegmentRecord[]; stored: boolean }> {
    const db = await this.openDb();
    const byKey = new Map<string, SegmentRecord>();
    if (db !== null) {
      await this.runTransaction("readonly", (store) => {
        return new Promise<void>((resolve, reject) => {
          const request = store.openCursor(IDBKeyRange.bound(prefix, prefix + "\uffff"));
          request.onsuccess = () => {
            const cursor = request.result;
            if (cursor) {
              const { compositeKey, ...rest } = cursor.value as SegmentRecord & {
                compositeKey: string;
              };
              byKey.set(compositeKey, rest);
              cursor.continue();
            } else {
              resolve();
            }
          };
          request.onerror = () => reject(request.error);
        });
      });
    }
    for (const [key, record] of this.memoryFallback) {
      if (key.startsWith(prefix)) byKey.set(key, record);
    }
    return { records: [...byKey.values()], stored: db !== null || !this.isBrowser() };
  }

  private async runTransaction<T>(
    mode: IDBTransactionMode,
    work: (store: IDBObjectStore) => T | PromiseLike<T> | IDBRequest<T>,
    storeName: string = STORE_NAME
  ): Promise<T> {
    const db = await this.openDb();
    if (!db) throw new Error("IndexedDB not available");

    return new Promise<T>((resolve, reject) => {
      const tx = db.transaction(storeName, mode);
      const store = tx.objectStore(storeName);

      const txDone = new Promise<void>((txResolve, txReject) => {
        tx.oncomplete = () => txResolve();
        tx.onerror = () => txReject(tx.error ?? new Error("IndexedDB transaction failed"));
        tx.onabort = () => txReject(tx.error ?? new Error("IndexedDB transaction aborted"));
      });

      let workResult: T | PromiseLike<T> | IDBRequest<T>;
      try {
        workResult = work(store);
      } catch (error) {
        reject(error);
        return;
      }

      // The IndexedDB callbacks naturally hand back IDBRequest objects, so we
      // accept that shape directly here rather than asking every call site to
      // wrap one in a Promise. Forgetting the wrapper used to silently degrade
      // verifyRoundTrip — the IDBRequest leaked through and the round-trip
      // check always failed, flipping the store to memory mode on every write.
      const valuePromise: Promise<T> =
        workResult instanceof IDBRequest
          ? new Promise<T>((vResolve, vReject) => {
              const req = workResult as IDBRequest<T>;
              req.onsuccess = () => vResolve(req.result);
              req.onerror = () => vReject(req.error ?? new Error("IndexedDB request failed"));
            })
          : Promise.resolve(workResult as T | PromiseLike<T>);

      // Abort the transaction on a value-side rejection so writes don't
      // half-commit; tx.onabort then surfaces the rejection through txDone.
      valuePromise.catch(() => {
        try {
          tx.abort();
        } catch {
          // The transaction may already have completed.
        }
      });

      Promise.all([valuePromise, txDone])
        .then(([value]) => resolve(value))
        .catch(reject);
    });
  }

  // ---- Journal: a running recording's parts, written chunk by chunk ----

  private journalKey(flowId: string, stepId: string, sessionId: string, partId: string): string {
    return `${flowId}::${stepId}::${sessionId}::${partId}`;
  }

  private chunkKey(key: string, seq: number): string {
    return `${key}::${seq.toString().padStart(6, "0")}`;
  }

  // One transaction over the journal's two stores; `work` issues its requests.
  private async runJournal(
    mode: IDBTransactionMode,
    work: (parts: IDBObjectStore, chunks: IDBObjectStore) => void
  ): Promise<void> {
    const db = await this.openDb();
    if (!db) throw new Error("IndexedDB not available");
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction([JOURNAL_PARTS, JOURNAL_CHUNKS], mode);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error("IndexedDB transaction failed"));
      tx.onabort = () => reject(tx.error ?? new Error("IndexedDB transaction aborted"));
      try {
        work(tx.objectStore(JOURNAL_PARTS), tx.objectStore(JOURNAL_CHUNKS));
      } catch (error) {
        try {
          tx.abort();
        } catch {
          // Already finished.
        }
        reject(error);
      }
    });
  }

  private async readAll<T>(storeName: string, range: IDBKeyRange): Promise<T[]> {
    const db = await this.openDb();
    if (!db) throw new Error("IndexedDB not available");
    return new Promise<T[]>((resolve, reject) => {
      const request = db.transaction(storeName, "readonly").objectStore(storeName).getAll(range);
      request.onsuccess = () => resolve(request.result as T[]);
      request.onerror = () => reject(request.error);
    });
  }

  // Null outside a browser, where memory is the whole ledger and nothing outlives the page.
  async beginJournalPart(
    part: Omit<JournalPart, "key" | "lastChunkAt" | "chunkCount">
  ): Promise<string | null> {
    if (!this.isBrowser()) return null;
    const key = this.journalKey(part.flowId, part.stepId, part.sessionId, part.partId);
    const meta: JournalPart = { ...part, key, lastChunkAt: part.startedAt, chunkCount: 0 };
    await this.runJournal("readwrite", (parts) => {
      parts.put(meta);
    });
    return key;
  }

  // The chunk and the part's count go in one transaction: a crash keeps both or neither.
  // Rejects when the chunk does not read back, as a stored part must.
  async appendJournalChunk(key: string, seq: number, blob: Blob, at: number): Promise<void> {
    const chunkKey = this.chunkKey(key, seq);
    await this.runJournal("readwrite", (parts, chunks) => {
      chunks.put({ key: chunkKey, blob, at });
      const get = parts.get(key);
      get.onsuccess = () => {
        const meta = get.result as JournalPart | undefined;
        if (meta) parts.put({ ...meta, lastChunkAt: at, chunkCount: seq + 1 });
      };
    });
    if (!(await this.verifyRoundTrip(chunkKey, blob.size, JOURNAL_CHUNKS))) {
      throw new Error("RecordingSessionStore: a journal chunk did not read back");
    }
  }

  // Metadata only: the scan never reads audio.
  async listJournalParts(flowId: string, stepId: string): Promise<JournalPart[]> {
    if (!this.isBrowser()) return [];
    const prefix = `${flowId}::${stepId}::`;
    return this.readAll<JournalPart>(JOURNAL_PARTS, IDBKeyRange.bound(prefix, prefix + "\uffff"));
  }

  // The run of chunks from the first that are in sequence and read back: a gap or a
  // chunk whose bytes are gone ends what can be played. Null when a chunk gave no
  // answer in time: the whole journal is kept for another try.
  async readJournalChunks(key: string): Promise<{ blob: Blob; at: number }[] | null> {
    const prefix = `${key}::`;
    const rows = await this.readAll<{ key: string; blob: Blob; at: number }>(
      JOURNAL_CHUNKS,
      IDBKeyRange.bound(prefix, prefix + "\uffff")
    );
    // Keys sort by their zero-padded sequence.
    const playable: { blob: Blob; at: number }[] = [];
    for (const [seq, row] of rows.entries()) {
      if (row.key !== this.chunkKey(key, seq)) break;
      const plays = await withinVerifyTime(readsBack(row.blob));
      if (plays === null) return null;
      if (!plays) break;
      playable.push({ blob: row.blob, at: row.at });
    }
    return playable;
  }

  async dropJournalPart(key: string): Promise<void> {
    const prefix = `${key}::`;
    await this.runJournal("readwrite", (parts, chunks) => {
      parts.delete(key);
      chunks.delete(IDBKeyRange.bound(prefix, prefix + "\uffff"));
    });
  }

  // A part the journal holds but the store does not becomes its recording's next
  // part: a closed tab, a reload or a crash cut it off. A stored copy counts only
  // when it reads back; one that does not is replaced in its place. The journal is
  // dropped once the part is stored, or when there is nothing to rebuild. False
  // when the part could not be stored: the journal stays for another try. The
  // caller holds the step's recovery lock, so no other tab numbers parts meanwhile.
  async recoverJournalPart(part: JournalPart, now: number = Date.now()): Promise<boolean> {
    const { records } = await this.readRange(
      this.sessionPrefix(part.flowId, part.stepId, part.sessionId)
    );
    const stored = records.find((r) => r.partId === part.partId);
    const segmentIndex =
      stored?.segmentIndex ?? Math.max(-1, ...records.map((r) => r.segmentIndex)) + 1;
    const compositeKey = this.compositeKey(part.flowId, part.stepId, part.sessionId, segmentIndex);
    // Only this tab's memory holds it: the journal stays, for after a reload.
    if (stored && this.memoryFallback.has(compositeKey)) return true;
    const kept = stored ? await this.verifyRoundTrip(compositeKey, stored.blob.size) : false;
    const expired = part.lastChunkAt < now - SESSION_TTL_MS;
    const chunks = kept || expired ? [] : await this.readJournalChunks(part.key);
    // Slow to read is not gone: nothing is replaced or dropped until an answer comes.
    if (kept === null || chunks === null) return false;
    // The part ends with its last chunk that plays, when the recorder handed it over.
    const savedUntil = chunks.at(-1)?.at ?? part.lastChunkAt;
    const durationMs = Math.max(0, savedUntil - part.startedAt);
    if (chunks.length > 0) {
      const [first, ...rest] = chunks.map((chunk) => chunk.blob);
      const { persisted } = await this.writeSegment({
        flowId: part.flowId,
        stepId: part.stepId,
        sessionId: part.sessionId,
        segmentIndex,
        blob: new Blob([await withRecordedDuration(first!, durationMs, part.mimeType), ...rest], {
          type: part.mimeType
        }),
        mimeType: part.mimeType,
        durationMs,
        capturedAt: savedUntil,
        uploadedFileId: null,
        reason: "interrupted",
        contractSnapshot: part.contractSnapshot,
        partId: part.partId
      });
      if (!persisted) {
        // The journal, not this tab's memory, stays the part's one copy.
        this.memoryFallback.delete(compositeKey);
        return false;
      }
    }
    await this.dropJournalPart(part.key);
    return true;
  }

  __resetForTests(): void {
    this.db?.close();
    this.db = null;
    this.openPromise = null;
    this.memoryFallback.clear();
  }

  __unpersistedCountForTests(): number {
    return this.memoryFallback.size;
  }
}

export const recordingSessionStore = new RecordingSessionStoreImpl();
export type RecordingSessionStore = RecordingSessionStoreImpl;

export const SESSION_RECOVERY_TTL_MS = SESSION_TTL_MS;
