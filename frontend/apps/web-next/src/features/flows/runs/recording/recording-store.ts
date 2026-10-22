/**
 * Where a recording made in the run form is kept on the device, so a closed
 * tab, a reload or a crash does not lose it: every finished part, and the
 * chunks of the part still being recorded (its journal). IndexedDB holds
 * them; `memoryRecordings` is the same contract in memory, for tests.
 *
 * Every write is read back before it counts: some browsers store a
 * reference to a temporary file instead of the bytes, and that reference
 * is gone after the tab closes. A read that gives no answer in time is
 * "unknown", never "gone".
 */

/** What the step asked of its files when the part was recorded. */
export type ContractSnapshot = {
  publishedFlowVersion: number | null;
  inputFormat: string | null;
  maxFiles: number | null;
  maxFileSizeBytes: number | null;
  acceptedMimetypes: string[];
};

/** Which recording a part belongs to, and where in it. */
export type PartAddress = {
  flowId: string;
  stepId: string;
  sessionId: string;
  index: number;
};

/** A finished part on the device. */
export type StoredPart = PartAddress & {
  blob: Blob;
  mimeType: string;
  durationMs: number;
  /** Wall-clock time at which the part started, which its file name carries. */
  capturedAt: number;
  /** Rebuilt from its journal: the page went away while it recorded. */
  interrupted: boolean;
  contract: ContractSnapshot;
};

/** The part being recorded, as its journal knows it without reading audio. */
export type JournalMeta = PartAddress & {
  mimeType: string;
  capturedAt: number;
  contract: ContractSnapshot;
  /** Wall-clock time of the last chunk written, for expiry. */
  lastChunkAt: number;
};

/** One chunk of a journal: its audio and the part's recorded time when it came. */
export type JournalChunk = { blob: Blob; recordedMs: number; at: number };

export type RecordingDatabase = {
  /** Stores a part, replacing one at the same address; rejects unless it reads back. */
  putPart(part: StoredPart): Promise<void>;
  /** A step's stored parts, in address order. */
  listParts(flowId: string, stepId: string): Promise<StoredPart[]>;
  /** Whether the part is stored and reads back; null when that is not known in time. */
  hasPart(address: PartAddress, size?: number): Promise<boolean | null>;
  deletePart(address: PartAddress): Promise<void>;
  /** Deletes a recording's parts and journals. */
  deleteSession(flowId: string, stepId: string, sessionId: string): Promise<void>;
  putJournal(meta: JournalMeta): Promise<void>;
  /** Writes chunk `seq` of a journal; rejects unless it reads back. */
  appendChunk(address: PartAddress, seq: number, chunk: JournalChunk): Promise<void>;
  listJournals(flowId: string, stepId: string): Promise<JournalMeta[]>;
  /**
   * The chunks from the first that are in sequence and read back; a gap or
   * a chunk whose bytes are gone ends what can be played. Null when a chunk
   * gave no answer in time.
   */
  readChunks(address: PartAddress): Promise<JournalChunk[] | null>;
  dropJournal(address: PartAddress): Promise<void>;
};

/** How long a recording stays on the device after its last activity. */
export const RECORDING_TTL_MS = 24 * 60 * 60 * 1000;
const READ_BACK_TIMEOUT_MS = 2_000;

const pad = (value: number, width: number) => String(value).padStart(width, "0");

export function sessionPrefix(flowId: string, stepId: string, sessionId: string): string {
  return `${flowId}::${stepId}::${sessionId}::`;
}

export function partKey({ flowId, stepId, sessionId, index }: PartAddress): string {
  return `${sessionPrefix(flowId, stepId, sessionId)}${pad(index, 4)}`;
}

function stepPrefix(flowId: string, stepId: string): string {
  return `${flowId}::${stepId}::`;
}

function chunkKey(address: PartAddress, seq: number): string {
  return `${partKey(address)}::${pad(seq, 6)}`;
}

/**
 * Whether a stored blob still has its bytes: reading one byte makes the
 * engine open them, so a blob that only referenced a lost temporary file
 * fails here and not at upload.
 */
export async function readsBack(blob: Blob, size?: number): Promise<boolean> {
  if (size !== undefined && blob.size !== size) return false;
  if (blob.size === 0) return true;
  try {
    return (await blob.slice(0, 1).arrayBuffer()).byteLength > 0;
  } catch {
    return false;
  }
}

/** The answer, or null when it did not come in time: slow is not the same as gone. */
function withinTime<T>(work: Promise<T>, ms = READ_BACK_TIMEOUT_MS): Promise<T | null> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), ms);
    work.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      () => {
        clearTimeout(timer);
        resolve(null);
      }
    );
  });
}

function compareAddress(a: PartAddress, b: PartAddress): number {
  return a.sessionId.localeCompare(b.sessionId) || a.index - b.index;
}

/** The same contract in memory: what a test reads back, and nothing outlives the page. */
export function memoryRecordings(): RecordingDatabase & {
  parts: Map<string, StoredPart>;
  journals: Map<string, JournalMeta>;
  chunks: Map<string, JournalChunk>;
} {
  const parts = new Map<string, StoredPart>();
  const journals = new Map<string, JournalMeta>();
  const chunks = new Map<string, JournalChunk>();
  const inRange = (key: string, prefix: string) => key.startsWith(prefix);
  return {
    parts,
    journals,
    chunks,
    async putPart(part) {
      parts.set(partKey(part), part);
    },
    async listParts(flowId, stepId) {
      return [...parts.entries()]
        .filter(([key]) => inRange(key, stepPrefix(flowId, stepId)))
        .map(([, part]) => part)
        .sort(compareAddress);
    },
    async hasPart(address, size) {
      const part = parts.get(partKey(address));
      return part ? readsBack(part.blob, size) : false;
    },
    async deletePart(address) {
      parts.delete(partKey(address));
    },
    async deleteSession(flowId, stepId, sessionId) {
      const prefix = sessionPrefix(flowId, stepId, sessionId);
      for (const map of [parts, journals, chunks] as Map<string, unknown>[]) {
        for (const key of [...map.keys()]) if (inRange(key, prefix)) map.delete(key);
      }
    },
    async putJournal(meta) {
      journals.set(partKey(meta), meta);
    },
    async appendChunk(address, seq, chunk) {
      chunks.set(chunkKey(address, seq), chunk);
      const meta = journals.get(partKey(address));
      if (meta) journals.set(partKey(address), { ...meta, lastChunkAt: chunk.at });
    },
    async listJournals(flowId, stepId) {
      return [...journals.entries()]
        .filter(([key]) => inRange(key, stepPrefix(flowId, stepId)))
        .map(([, meta]) => meta)
        .sort(compareAddress);
    },
    async readChunks(address) {
      const playable: JournalChunk[] = [];
      for (let seq = 0; ; seq += 1) {
        const chunk = chunks.get(chunkKey(address, seq));
        if (!chunk || !(await readsBack(chunk.blob))) return playable;
        playable.push(chunk);
      }
    },
    async dropJournal(address) {
      const key = partKey(address);
      journals.delete(key);
      for (const chunk of [...chunks.keys()]) if (inRange(chunk, `${key}::`)) chunks.delete(chunk);
    }
  };
}

const DB_NAME = "eneo-flow-recordings";
const DB_VERSION = 1;
const PARTS = "parts";
const JOURNALS = "journals";
const CHUNKS = "chunks";

function range(prefix: string): IDBKeyRange {
  return IDBKeyRange.bound(prefix, `${prefix}￿`);
}

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("IndexedDB request failed"));
  });
}

/** Runs `work` in one transaction over `stores` and settles once it has committed. */
function transaction<T>(
  db: IDBDatabase,
  stores: string[],
  mode: IDBTransactionMode,
  work: (tx: IDBTransaction) => Promise<T> | T
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let tx: IDBTransaction;
    try {
      tx = db.transaction(stores, mode);
    } catch (error) {
      reject(error);
      return;
    }
    let result: T;
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error ?? new Error("IndexedDB transaction failed"));
    tx.onabort = () => reject(tx.error ?? new Error("IndexedDB transaction aborted"));
    Promise.resolve()
      .then(() => work(tx))
      .then(
        (value) => {
          result = value;
        },
        (error: unknown) => {
          try {
            tx.abort();
          } catch {
            // Already finished.
          }
          reject(error);
        }
      );
  });
}

/**
 * The device's store, or null where the browser has no IndexedDB. A store
 * that cannot be opened (private mode, blocked site data) rejects every
 * call, which callers read as "kept only in this tab".
 */
export function indexedDbRecordings(): RecordingDatabase | null {
  let factory: IDBFactory | undefined;
  try {
    factory = typeof indexedDB === "undefined" ? undefined : indexedDB;
  } catch {
    factory = undefined;
  }
  if (!factory) return null;
  const idb = factory;
  let opening: Promise<IDBDatabase> | null = null;

  function open(): Promise<IDBDatabase> {
    opening ??= new Promise<IDBDatabase>((resolve, reject) => {
      let req: IDBOpenDBRequest;
      try {
        req = idb.open(DB_NAME, DB_VERSION);
      } catch (error) {
        reject(error);
        return;
      }
      req.onupgradeneeded = () => {
        const db = req.result;
        for (const store of [PARTS, JOURNALS, CHUNKS]) {
          if (!db.objectStoreNames.contains(store)) db.createObjectStore(store);
        }
      };
      req.onsuccess = () => {
        const db = req.result;
        // Another tab opening a newer version: let it, and open again when needed.
        db.onversionchange = () => {
          db.close();
          opening = null;
        };
        resolve(db);
      };
      req.onerror = () => reject(req.error ?? new Error("IndexedDB did not open"));
      req.onblocked = () => reject(new Error("IndexedDB is blocked by another tab"));
    });
    // A failed open is not kept: the next call tries again.
    opening.catch(() => {
      opening = null;
    });
    return opening;
  }

  async function readBack(store: string, key: string, size: number): Promise<boolean | null> {
    const db = await open();
    return withinTime(
      transaction(db, [store], "readonly", (tx) =>
        request(tx.objectStore(store).get(key) as IDBRequest<{ blob?: unknown } | undefined>)
      ).then((value) => {
        const blob = value?.blob;
        return blob instanceof Blob ? readsBack(blob, size) : false;
      })
    );
  }

  async function getAll<T>(store: string, prefix: string): Promise<T[]> {
    const db = await open();
    return transaction(db, [store], "readonly", (tx) =>
      request(tx.objectStore(store).getAll(range(prefix)) as IDBRequest<T[]>)
    );
  }

  return {
    async putPart(part) {
      const db = await open();
      const key = partKey(part);
      await transaction(db, [PARTS], "readwrite", (tx) => {
        tx.objectStore(PARTS).put(part, key);
      });
      if ((await readBack(PARTS, key, part.blob.size)) !== true) {
        throw new Error("A stored part did not read back");
      }
    },
    async listParts(flowId, stepId) {
      return (await getAll<StoredPart>(PARTS, stepPrefix(flowId, stepId))).sort(compareAddress);
    },
    async hasPart(address, size) {
      const db = await open();
      const part = await withinTime(
        transaction(db, [PARTS], "readonly", (tx) =>
          request(tx.objectStore(PARTS).get(partKey(address)) as IDBRequest<StoredPart | undefined>)
        )
      );
      if (part === null) return null;
      if (!part) return false;
      return withinTime(readsBack(part.blob, size));
    },
    async deletePart(address) {
      const db = await open();
      await transaction(db, [PARTS], "readwrite", (tx) => {
        tx.objectStore(PARTS).delete(partKey(address));
      });
    },
    async deleteSession(flowId, stepId, sessionId) {
      const db = await open();
      const prefix = sessionPrefix(flowId, stepId, sessionId);
      await transaction(db, [PARTS, JOURNALS, CHUNKS], "readwrite", (tx) => {
        for (const store of [PARTS, JOURNALS, CHUNKS]) tx.objectStore(store).delete(range(prefix));
      });
    },
    async putJournal(meta) {
      const db = await open();
      await transaction(db, [JOURNALS], "readwrite", (tx) => {
        tx.objectStore(JOURNALS).put(meta, partKey(meta));
      });
    },
    async appendChunk(address, seq, chunk) {
      const db = await open();
      const key = chunkKey(address, seq);
      // The chunk and the journal's activity go together: a crash keeps both or neither.
      await transaction(db, [JOURNALS, CHUNKS], "readwrite", async (tx) => {
        tx.objectStore(CHUNKS).put(chunk, key);
        const journals = tx.objectStore(JOURNALS);
        const meta = await request(
          journals.get(partKey(address)) as IDBRequest<JournalMeta | undefined>
        );
        if (meta) journals.put({ ...meta, lastChunkAt: chunk.at }, partKey(address));
      });
      if ((await readBack(CHUNKS, key, chunk.blob.size)) !== true) {
        throw new Error("A journal chunk did not read back");
      }
    },
    async listJournals(flowId, stepId) {
      return (await getAll<JournalMeta>(JOURNALS, stepPrefix(flowId, stepId))).sort(compareAddress);
    },
    async readChunks(address) {
      const prefix = `${partKey(address)}::`;
      const db = await open();
      const rows = await transaction(db, [CHUNKS], "readonly", async (tx) => {
        const store = tx.objectStore(CHUNKS);
        const [keys, values] = await Promise.all([
          request(store.getAllKeys(range(prefix))),
          request(store.getAll(range(prefix)) as IDBRequest<JournalChunk[]>)
        ]);
        return keys.map((key, at) => ({ key: String(key), chunk: values[at]! }));
      });
      const playable: JournalChunk[] = [];
      for (const [seq, row] of rows.entries()) {
        // Keys sort by their zero-padded sequence: a missing one is a gap.
        if (row.key !== chunkKey(address, seq)) break;
        const plays = await withinTime(readsBack(row.chunk.blob));
        if (plays === null) return null;
        if (!plays) break;
        playable.push(row.chunk);
      }
      return playable;
    },
    async dropJournal(address) {
      const db = await open();
      const key = partKey(address);
      await transaction(db, [JOURNALS, CHUNKS], "readwrite", (tx) => {
        tx.objectStore(JOURNALS).delete(key);
        tx.objectStore(CHUNKS).delete(range(`${key}::`));
      });
    }
  };
}
