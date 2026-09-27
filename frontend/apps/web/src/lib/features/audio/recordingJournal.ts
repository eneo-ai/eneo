// The journal of a running recording: every chunk the recorder hands over is
// written to the device as it arrives, so a crash, a reload or a closed tab
// loses at most the chunks still queued, not the part. Chunks go in order,
// one part's queue at a time; the finished part, once stored, drops its journal.

import type { JournalPart } from "./recordingSessionStore";

// At the recorder's 2 s timeslice, 30 s of audio: more waiting than that means
// storage cannot keep up. The part stops journaling (what it wrote stays) and the
// dialog says so.
export const JOURNAL_MAX_PENDING_CHUNKS = 15;

// Named by the part, so the lock is taken before the part's first write.
export const journalLockName = (partId: string) => `eneo-recording-journal:${partId}`;

// A cut-off WebM/Opus recording is shown to play up to its last chunk; a cut-off
// MP4 (Safari) is not yet, so its parts are not journaled.
const JOURNALED_TYPE = /^(audio|video)\/webm\b/;

// How long a part the recorder left waits for its lock, to write what it captured.
const LEAVE_LOCK_WAIT_MS = 2_000;

// "failed": storage refused or fell behind, so the rest of a part is only in this tab;
// "unavailable": this browser keeps a part on the device only once it is done.
export type JournalDegradation = "failed" | "unavailable";

// What the recorder tells the journal about the segment it records.
export type RecorderJournal = {
  begin(partId: string, mimeType: string): void;
  append(partId: string, blob: Blob): void;
  // The recorder went away while recording: the part stays, to be rebuilt later.
  leave(partId: string): void;
  discard(partId: string): void;
};

type JournalStore = {
  beginJournalPart(
    part: Omit<JournalPart, "key" | "lastChunkAt" | "chunkCount">
  ): Promise<string | null>;
  appendJournalChunk(key: string, seq: number, blob: Blob, at: number): Promise<void>;
  dropJournalPart(key: string): Promise<void>;
};

type JournalledPart = {
  key: Promise<string | null>;
  tail: Promise<void>;
  pending: number;
  seq: number;
  // No new chunks: storage fell behind, a write failed or the lock was refused.
  stopped: boolean;
  // A write failed: later chunks would leave a gap, so none is written.
  failed: boolean;
  // The part ended: a lock granted from now on is let go at once.
  ended: boolean;
  partId: string;
  stepId: string;
  // Settles the wait for the lock: a part dropped before it, or left without it in
  // time, writes nothing (the latter says so).
  settleGrant: (held: boolean) => void;
  releaseLock: () => void;
};

export class RecordingJournal {
  #parts = new Map<string, JournalledPart>();

  constructor(
    private readonly store: JournalStore,
    // Once for a part: what it wrote stays, the rest of it is only in this tab until
    // the part is stored.
    private readonly onDegraded: (
      reason: JournalDegradation,
      partId: string,
      stepId: string
    ) => void,
    // The recording tab holds each part's lock: recovery in another tab skips a
    // part whose lock is held. Without Web Locks nothing is journaled.
    private readonly locks: LockManager | null = (globalThis.navigator as Navigator | undefined)
      ?.locks ?? null
  ) {}

  begin(partId: string, meta: Omit<JournalPart, "key" | "partId" | "lastChunkAt" | "chunkCount">) {
    const locks = this.locks;
    if (!locks || !JOURNALED_TYPE.test(meta.mimeType)) {
      return this.onDegraded("unavailable", partId, meta.stepId);
    }
    const part: JournalledPart = {
      key: Promise.resolve(null),
      tail: Promise.resolve(),
      pending: 0,
      seq: 0,
      stopped: false,
      failed: false,
      ended: false,
      partId,
      stepId: meta.stepId,
      settleGrant: () => {},
      releaseLock: () => {}
    };
    this.#parts.set(partId, part);
    // Nothing is written before the lock is held, so a scan in another tab never
    // takes over a part still recording. A refused lock publishes no part.
    const granted = new Promise<boolean>((resolve) => {
      part.settleGrant = resolve;
      locks
        .request(
          journalLockName(partId),
          () =>
            new Promise<void>((release) => {
              part.releaseLock = release;
              resolve(true);
              if (part.ended) release();
            })
        )
        .catch((error) => {
          console.warn("RecordingJournal: a part's lock was refused", error);
          resolve(false);
        });
    });
    part.key = granted.then(async (held) => {
      if (!held) {
        if (!part.ended) this.#stop(part);
        return null;
      }
      // Null: no journal here (outside a browser); a rejection: the device refused it.
      return this.store.beginJournalPart({ ...meta, partId }).catch((error) => {
        console.warn("RecordingJournal: a part could not be started", error);
        this.#stop(part);
        return null;
      });
    });
    part.tail = part.key.then(() => undefined);
  }

  append(partId: string, blob: Blob): void {
    const part = this.#parts.get(partId);
    if (!part || part.stopped) return;
    if (part.pending >= JOURNAL_MAX_PENDING_CHUNKS) return this.#stop(part);
    const seq = part.seq++;
    // When the recorder handed the chunk over: what a rebuilt part is saved up to.
    const at = Date.now();
    part.pending += 1;
    part.tail = part.tail.then(async () => {
      const key = await part.key;
      if (!key || part.failed) return;
      try {
        await this.store.appendJournalChunk(key, seq, blob, at);
      } catch (error) {
        console.warn("RecordingJournal: a chunk could not be written", error);
        part.failed = true;
        this.#stop(part);
      } finally {
        part.pending -= 1;
      }
    });
  }

  // The finished part is stored: its journal is no longer needed.
  commit(partId: string): Promise<void> {
    return this.#end(partId, true);
  }

  leave(partId: string): Promise<void> {
    return this.#end(partId, false);
  }

  // The part's audio is not kept (the recording was discarded): nor is its journal.
  discard(partId: string): Promise<void> {
    return this.#end(partId, true);
  }

  // Its queued chunks are written first; the lock is held until the journal is dropped.
  async #end(partId: string, drop: boolean): Promise<void> {
    const part = this.#parts.get(partId);
    if (!part) return;
    this.#parts.delete(partId);
    // A part whose audio is dropped needs no lock it does not hold yet; one that is
    // left waits a bounded time for it, to write what the recorder captured.
    if (drop) {
      part.ended = true;
      part.settleGrant(false);
    } else {
      setTimeout(() => part.settleGrant(false), LEAVE_LOCK_WAIT_MS);
    }
    await part.tail;
    const key = await part.key;
    if (drop && key) {
      await this.store.dropJournalPart(key).catch((error) => {
        // Left for recovery, which finds the part stored and only drops the journal.
        console.warn("RecordingJournal: a part's journal could not be dropped", error);
      });
    }
    part.ended = true;
    part.releaseLock();
  }

  #stop(part: JournalledPart): void {
    if (part.stopped) return;
    part.stopped = true;
    this.onDegraded("failed", part.partId, part.stepId);
  }
}
