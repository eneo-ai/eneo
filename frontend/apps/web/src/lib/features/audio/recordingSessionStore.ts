// IndexedDB-backed segment ledger with memory fallback when Blob round-trip fails.

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
  private mode: StoreMode = "indexeddb";
  private memoryFallback = new Map<string, SegmentRecord>();
  private openPromise: Promise<IDBDatabase | null> | null = null;

  get currentMode(): StoreMode {
    return this.mode;
  }

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
    if (!this.isBrowser()) {
      this.mode = "memory";
      return null;
    }
    if (this.db) return this.db;
    if (this.openPromise) return this.openPromise;

    this.openPromise = new Promise<IDBDatabase | null>((resolve) => {
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
          this.db = request.result;
          this.mode = "indexeddb";
          resolve(this.db);
        };
        request.onerror = () => {
          console.warn("RecordingSessionStore: indexedDB.open failed", request.error);
          this.mode = "memory";
          resolve(null);
        };
        request.onblocked = () => {
          console.warn("RecordingSessionStore: indexedDB.open blocked, using memory");
          this.mode = "memory";
          resolve(null);
        };
      } catch (error) {
        console.warn("RecordingSessionStore: indexedDB.open threw, using memory", error);
        this.mode = "memory";
        resolve(null);
      }
    });

    return this.openPromise;
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
    const expectedSize = record.blob.size;

    this.memoryFallback.set(compositeKey, record);

    const db = await this.openDb();
    if (db === null || this.mode === "memory") {
      return { persisted: false, mode: "memory" };
    }

    try {
      await this.runTransaction("readwrite", (store) => {
        store.put({ ...record, compositeKey });
      });
    } catch (error) {
      console.warn("RecordingSessionStore: write failed, falling back to memory", error);
      this.mode = "memory";
      return { persisted: false, mode: "memory" };
    }

    try {
      const verified = await this.verifyRoundTrip(compositeKey, expectedSize);
      if (!verified) {
        console.warn(
          "RecordingSessionStore: Blob round-trip verification failed, falling back to memory"
        );
        this.mode = "memory";
        return { persisted: false, mode: "memory" };
      }
    } catch (error) {
      console.warn("RecordingSessionStore: round-trip verify threw, falling back to memory", error);
      this.mode = "memory";
      return { persisted: false, mode: "memory" };
    }

    return { persisted: true, mode: "indexeddb" };
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
    const prefix = this.sessionPrefix(flowId, stepId, sessionId);

    if (this.mode === "memory" || (await this.openDb()) === null) {
      return Array.from(this.memoryFallback.values())
        .filter((r) => r.flowId === flowId && r.stepId === stepId && r.sessionId === sessionId)
        .sort((a, b) => a.segmentIndex - b.segmentIndex);
    }

    try {
      return await this.runTransaction("readonly", (store) => {
        return new Promise<SegmentRecord[]>((resolve, reject) => {
          const results: SegmentRecord[] = [];
          const range = IDBKeyRange.bound(prefix, prefix + "￿");
          const request = store.openCursor(range);
          request.onsuccess = () => {
            const cursor = request.result;
            if (cursor) {
              const value = cursor.value as SegmentRecord & { compositeKey: string };
              const { compositeKey: _drop, ...rest } = value;
              results.push(rest);
              cursor.continue();
            } else {
              results.sort((a, b) => a.segmentIndex - b.segmentIndex);
              resolve(results);
            }
          };
          request.onerror = () => reject(request.error);
        });
      });
    } catch (error) {
      console.warn("RecordingSessionStore: readSession failed, using memory", error);
      this.mode = "memory";
      return this.readSession(flowId, stepId, sessionId);
    }
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

    if (this.mode === "memory" || (await this.openDb()) === null) return;

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

    if (this.mode === "memory" || (await this.openDb()) === null) return true;

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

  async deleteSession(flowId: string, stepId: string, sessionId: string): Promise<void> {
    const prefix = this.sessionPrefix(flowId, stepId, sessionId);
    for (const key of Array.from(this.memoryFallback.keys())) {
      if (key.startsWith(prefix)) this.memoryFallback.delete(key);
    }

    if (this.mode === "memory" || (await this.openDb()) === null) return;

    try {
      await this.runTransaction("readwrite", (store) => {
        return new Promise<void>((resolve, reject) => {
          const range = IDBKeyRange.bound(prefix, prefix + "￿");
          const request = store.delete(range);
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        });
      });
    } catch (error) {
      console.warn("RecordingSessionStore: deleteSession failed", error);
    }
  }

  async listRecoverableSessions(
    flowId: string,
    stepId: string,
    now: number = Date.now()
  ): Promise<SessionRecoveryHint[]> {
    const cutoff = now - SESSION_TTL_MS;
    const segments = await this._readAllSegments(flowId, stepId);
    if (segments === null) return [];

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
        void this.deleteSession(flowId, stepId, sessionId);
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

  async cleanupExpired(now: number = Date.now()): Promise<number> {
    const cutoff = now - SESSION_TTL_MS;

    // We can't trust the `by_capturedAt` index for cleanup because it
    // would delete individual old segments inside an otherwise-fresh
    // session, leaving a partial recording with holes. Group every
    // segment by (flowId, stepId, sessionId) first and only delete the
    // session if its latest activity is past cutoff.
    type SessionKey = string;
    const sessionKey = (s: SegmentRecord): SessionKey => `${s.flowId}::${s.stepId}::${s.sessionId}`;
    const latestPerSession = new Map<
      SessionKey,
      { flowId: string; stepId: string; sessionId: string; latestCapturedAt: number }
    >();
    const visit = (record: SegmentRecord) => {
      const key = sessionKey(record);
      const prior = latestPerSession.get(key);
      if (!prior || record.capturedAt > prior.latestCapturedAt) {
        latestPerSession.set(key, {
          flowId: record.flowId,
          stepId: record.stepId,
          sessionId: record.sessionId,
          latestCapturedAt: record.capturedAt
        });
      }
    };
    for (const record of this.memoryFallback.values()) visit(record);

    if (this.mode !== "memory") {
      const db = await this.openDb();
      if (db !== null) {
        try {
          await this.runTransaction("readonly", (store) => {
            return new Promise<void>((resolve, reject) => {
              const request = store.openCursor();
              request.onsuccess = () => {
                const cursor = request.result;
                if (cursor) {
                  const value = cursor.value as SegmentRecord & { compositeKey: string };
                  const { compositeKey: _drop, ...rest } = value;
                  visit(rest);
                  cursor.continue();
                } else {
                  resolve();
                }
              };
              request.onerror = () => reject(request.error);
            });
          });
        } catch (error) {
          console.warn("RecordingSessionStore: cleanupExpired walk failed", error);
        }
      }
    }

    let removed = 0;
    for (const session of latestPerSession.values()) {
      if (session.latestCapturedAt >= cutoff) continue;
      const before = this.memoryFallback.size;
      await this.deleteSession(session.flowId, session.stepId, session.sessionId);
      removed += before - this.memoryFallback.size;
    }
    return removed;
  }

  private async _readAllSegments(flowId: string, stepId: string): Promise<SegmentRecord[] | null> {
    if (this.mode === "memory" || (await this.openDb()) === null) {
      return Array.from(this.memoryFallback.values()).filter(
        (r) => r.flowId === flowId && r.stepId === stepId
      );
    }
    try {
      return await this.runTransaction("readonly", (store) => {
        return new Promise<SegmentRecord[]>((resolve, reject) => {
          const results: SegmentRecord[] = [];
          const prefix = `${flowId}::${stepId}::`;
          const range = IDBKeyRange.bound(prefix, prefix + "￿");
          const request = store.openCursor(range);
          request.onsuccess = () => {
            const cursor = request.result;
            if (cursor) {
              const value = cursor.value as SegmentRecord & { compositeKey: string };
              const { compositeKey: _drop, ...rest } = value;
              results.push(rest);
              cursor.continue();
            } else {
              resolve(results);
            }
          };
          request.onerror = () => reject(request.error);
        });
      });
    } catch (error) {
      console.warn("RecordingSessionStore: _readAllSegments failed", error);
      return null;
    }
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
    this.mode = "indexeddb";
    this.memoryFallback.clear();
  }
}

export const recordingSessionStore = new RecordingSessionStoreImpl();
export type RecordingSessionStore = RecordingSessionStoreImpl;

export const SESSION_RECOVERY_TTL_MS = SESSION_TTL_MS;
