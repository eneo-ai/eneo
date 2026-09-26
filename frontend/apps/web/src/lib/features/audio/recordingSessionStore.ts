// IndexedDB-backed segment ledger. Memory holds only the parts IndexedDB could not
// store (a failed write or Blob round trip), and every read combines the two.

import type { RecordingStopReason } from "./recordedAudioFile";

const DB_NAME = "eneo-recording-sessions";
const DB_VERSION = 1;
const STORE_NAME = "segments";
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
  earliestCapturedAt: number;
  uploadedCount: number;
  contractSnapshot: ContractSnapshot;
};

export type StoreMode = "indexeddb" | "memory";

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
        };
        request.onsuccess = () => {
          // A blocked attempt can still open after a later one did: keep one connection.
          if (this.db) request.result.close();
          else this.db = request.result;
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

  private async verifyRoundTrip(compositeKey: string, expectedSize: number): Promise<boolean> {
    // runTransaction now normalizes IDBRequest → Promise<value> and waits for
    // the transaction to complete, so the work fn can hand the request back
    // directly. The cast resolves to the stored object, not the IDBRequest.
    const fetched = await Promise.race([
      this.runTransaction<unknown>("readonly", (store) => store.get(compositeKey)),
      new Promise<undefined>((resolve) =>
        setTimeout(() => resolve(undefined), ROUND_TRIP_VERIFY_TIMEOUT_MS)
      )
    ]);

    const record = (fetched as { blob?: Blob } | undefined) ?? undefined;
    if (!record || !(record.blob instanceof Blob)) return false;
    if (record.blob.size !== expectedSize) return false;
    if (expectedSize === 0) return true;

    // Reading even one byte forces the engine to materialize the underlying
    // file handle; lazy-Blob bugs surface here instead of at upload time.
    try {
      const slice = record.blob.slice(0, Math.min(1, expectedSize));
      const buffer = await slice.arrayBuffer();
      return buffer.byteLength > 0;
    } catch {
      return false;
    }
  }

  async readSession(flowId: string, stepId: string, sessionId: string): Promise<SegmentRecord[]> {
    const records = await this.readRange(this.sessionPrefix(flowId, stepId, sessionId));
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

    if ((await this.openDb()) === null) return;

    try {
      await this.runTransaction("readwrite", (store) => {
        return new Promise<void>((resolve, reject) => {
          const get = store.get(compositeKey);
          get.onsuccess = () => {
            const record = get.result as (SegmentRecord & { compositeKey: string }) | undefined;
            if (!record) {
              resolve();
              return;
            }
            const put = store.put({ ...record, uploadedFileId });
            put.onsuccess = () => resolve();
            put.onerror = () => reject(put.error);
          };
          get.onerror = () => reject(get.error);
        });
      });
    } catch (error) {
      console.warn("RecordingSessionStore: patchUploadedFileId failed", error);
    }
  }

  // Drops the single record whose uploadedFileId matches. Used when the
  // user removes a recorded segment from the dialog — without this, the
  // IDB ledger keeps the upload reference and resume re-attaches the
  // deleted audio. Returns true if a record was actually deleted.
  async detachUploadedFileId(
    flowId: string,
    stepId: string,
    sessionId: string,
    uploadedFileId: string
  ): Promise<boolean> {
    if (!uploadedFileId) return false;
    const records = await this.readSession(flowId, stepId, sessionId);
    const match = records.find((r) => r.uploadedFileId === uploadedFileId);
    if (!match) return false;

    const compositeKey = this.compositeKey(flowId, stepId, sessionId, match.segmentIndex);
    this.memoryFallback.delete(compositeKey);

    if ((await this.openDb()) === null) return true;

    try {
      await this.runTransaction("readwrite", (store) => {
        return new Promise<void>((resolve, reject) => {
          const request = store.delete(compositeKey);
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        });
      });
    } catch (error) {
      console.warn("RecordingSessionStore: detachUploadedFileId failed", error);
    }
    return true;
  }

  // Rejects when IndexedDB could not delete the stored parts; the parts only memory
  // holds are then kept too, so the whole session stays for another try.
  async deleteSession(flowId: string, stepId: string, sessionId: string): Promise<void> {
    const prefix = this.sessionPrefix(flowId, stepId, sessionId);
    if ((await this.openDb()) !== null) {
      await this.runTransaction("readwrite", (store) => {
        return new Promise<void>((resolve, reject) => {
          const request = store.delete(IDBKeyRange.bound(prefix, prefix + "\uffff"));
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        });
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
  ): Promise<SessionRecoveryHint[]> {
    const cutoff = now - SESSION_TTL_MS;
    const segments = await this.readRange(`${flowId}::${stepId}::`);

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
      const earliestCapturedAt = Math.min(...list.map((s) => s.capturedAt));
      const uploadedCount = list.filter((s) => s.uploadedFileId !== null).length;
      hints.push({
        flowId,
        stepId,
        sessionId,
        segmentCount: list.length,
        totalDurationMs,
        earliestCapturedAt,
        uploadedCount,
        contractSnapshot: list[0]?.contractSnapshot ?? {
          publishedFlowVersion: null,
          maxFiles: null,
          maxFileSizeBytes: null,
          acceptedMimetypes: [],
          inputFormat: null
        }
      });
    }

    hints.sort((a, b) => b.earliestCapturedAt - a.earliestCapturedAt);
    return hints;
  }

  // Every part whose composite key starts with `prefix`: the stored ones and the ones
  // only memory holds (memory wins for the same key). A read IndexedDB started but could
  // not finish rejects: stored parts have no copy in memory, so part of a recording must
  // not pass for all of it. When IndexedDB does not open, this tab stored nothing there,
  // and memory holds everything it recorded.
  private async readRange(prefix: string): Promise<SegmentRecord[]> {
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
    return [...byKey.values()];
  }

  private async runTransaction<T>(
    mode: IDBTransactionMode,
    work: (store: IDBObjectStore) => T | PromiseLike<T> | IDBRequest<T>
  ): Promise<T> {
    const db = await this.openDb();
    if (!db) throw new Error("IndexedDB not available");

    return new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, mode);
      const store = tx.objectStore(STORE_NAME);

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
