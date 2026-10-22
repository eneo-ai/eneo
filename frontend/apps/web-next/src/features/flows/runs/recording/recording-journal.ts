import {
  partKey,
  type JournalMeta,
  type PartAddress,
  type RecordingDatabase
} from "./recording-store";

/**
 * The journal of the part being recorded: every chunk the recorder hands
 * over is written to the device as it arrives, so a crash, a reload or a
 * closed tab loses at most the chunks still queued, not the part. Chunks go
 * in order, one part's queue at a time; the finished part, once stored,
 * drops its journal (`commit`).
 *
 * The recording tab holds a Web Lock per part while it records, so recovery
 * in another tab never takes over a part still being recorded. Without Web
 * Locks nothing is journaled, and neither is audio a cut-off file of which
 * would not play (only WebM plays up to its last chunk).
 */

/**
 * At the recorder's one-second chunks, half a minute of audio waiting for
 * storage means it cannot keep up: the part stops journaling (what it wrote
 * stays) and the form says so.
 */
export const JOURNAL_MAX_PENDING_CHUNKS = 30;
const JOURNALED_TYPE = /^(audio|video)\/webm\b/;
/** How long a part the page left waits for its lock, to write what it captured. */
const LEAVE_LOCK_WAIT_MS = 2_000;

/** The lock the recording tab holds while a part records. */
export function journalLockName(address: PartAddress): string {
  return `eneo-flow-recording:${partKey(address)}`;
}

/**
 * "failed": storage refused or fell behind, so the rest of the part is only
 * in this tab; "unavailable": this browser keeps a part on the device only
 * once it is done.
 */
export type JournalDegradation = "failed" | "unavailable";

export type JournalLocks = Pick<LockManager, "request">;

type Entry = {
  address: PartAddress;
  ready: Promise<boolean>;
  tail: Promise<void>;
  pending: number;
  seq: number;
  /** No new chunks: storage fell behind, a write failed or the lock was refused. */
  stopped: boolean;
  /** A write failed: later chunks would leave a gap, so none is written. */
  failed: boolean;
  /** The part ended: a lock granted from now on is let go at once. */
  ended: boolean;
  settleGrant: (held: boolean) => void;
  releaseLock: () => void;
};

export function browserLocks(): JournalLocks | null {
  try {
    return typeof navigator === "undefined" ? null : (navigator.locks ?? null);
  } catch {
    return null;
  }
}

export class RecordingJournal {
  #entries = new Map<string, Entry>();
  #db: RecordingDatabase;
  #locks: JournalLocks | null;
  #onDegraded: (reason: JournalDegradation, address: PartAddress) => void;
  #now: () => number;

  constructor(
    db: RecordingDatabase,
    onDegraded: (reason: JournalDegradation, address: PartAddress) => void,
    locks: JournalLocks | null = browserLocks(),
    now: () => number = Date.now
  ) {
    this.#db = db;
    this.#onDegraded = onDegraded;
    this.#locks = locks;
    this.#now = now;
  }

  begin(meta: Omit<JournalMeta, "lastChunkAt">): void {
    const locks = this.#locks;
    if (!locks || !JOURNALED_TYPE.test(meta.mimeType)) {
      this.#onDegraded("unavailable", meta);
      return;
    }
    const address: PartAddress = {
      flowId: meta.flowId,
      stepId: meta.stepId,
      sessionId: meta.sessionId,
      index: meta.index
    };
    const entry: Entry = {
      address,
      ready: Promise.resolve(false),
      tail: Promise.resolve(),
      pending: 0,
      seq: 0,
      stopped: false,
      failed: false,
      ended: false,
      settleGrant: () => undefined,
      releaseLock: () => undefined
    };
    this.#entries.set(partKey(address), entry);
    // Nothing is written before the lock is held; a refused lock writes nothing.
    const granted = new Promise<boolean>((resolve) => {
      entry.settleGrant = resolve;
      try {
        locks
          .request(
            journalLockName(address),
            () =>
              new Promise<void>((release) => {
                entry.releaseLock = release;
                resolve(true);
                if (entry.ended) release();
              })
          )
          .catch(() => resolve(false));
      } catch {
        resolve(false);
      }
    });
    entry.ready = granted.then(async (held) => {
      if (!held) {
        if (!entry.ended) this.#stop(entry);
        return false;
      }
      try {
        await this.#db.putJournal({ ...meta, lastChunkAt: meta.capturedAt });
        return true;
      } catch {
        this.#stop(entry);
        return false;
      }
    });
    entry.tail = entry.ready.then(() => undefined);
  }

  append(address: PartAddress, blob: Blob, recordedMs: number): void {
    const entry = this.#entries.get(partKey(address));
    if (!entry || entry.stopped) return;
    if (entry.pending >= JOURNAL_MAX_PENDING_CHUNKS) {
      this.#stop(entry);
      return;
    }
    const seq = entry.seq++;
    const at = this.#now();
    entry.pending += 1;
    entry.tail = entry.tail.then(async () => {
      try {
        if (!(await entry.ready) || entry.failed) return;
        await this.#db.appendChunk(address, seq, { blob, recordedMs, at });
      } catch {
        entry.failed = true;
        this.#stop(entry);
      } finally {
        entry.pending -= 1;
      }
    });
  }

  /** The finished part is stored: its journal is no longer needed. */
  commit(address: PartAddress): Promise<void> {
    return this.#end(address, true);
  }

  /** The page goes away while the part records: it stays, to be rebuilt later. */
  leave(address: PartAddress): Promise<void> {
    return this.#end(address, false);
  }

  /** The part's audio is not kept: nor is its journal. */
  discard(address: PartAddress): Promise<void> {
    return this.#end(address, true);
  }

  /** Every part of a recording ends its journal, dropped; settles once none writes any more. */
  async discardSession(flowId: string, stepId: string, sessionId: string): Promise<void> {
    await Promise.all(
      [...this.#entries.values()]
        .filter(
          ({ address }) =>
            address.flowId === flowId &&
            address.stepId === stepId &&
            address.sessionId === sessionId
        )
        .map(({ address }) => this.discard(address))
    );
  }

  async #end(address: PartAddress, drop: boolean): Promise<void> {
    const entry = this.#entries.get(partKey(address));
    if (!entry) return;
    this.#entries.delete(partKey(address));
    if (drop) {
      // A part whose audio is dropped needs no lock it does not hold yet.
      entry.ended = true;
      entry.settleGrant(false);
    } else {
      // One that is left waits a bounded time for it, to write what it captured.
      setTimeout(() => entry.settleGrant(false), LEAVE_LOCK_WAIT_MS);
    }
    await entry.tail;
    if (drop && (await entry.ready)) {
      // Left for recovery, which finds the part stored and only drops the journal.
      await this.#db.dropJournal(address).catch(() => undefined);
    }
    entry.ended = true;
    entry.releaseLock();
  }

  #stop(entry: Entry): void {
    if (entry.stopped) return;
    entry.stopped = true;
    this.#onDegraded("failed", entry.address);
  }
}
