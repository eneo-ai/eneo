import type { RuntimeInput } from "../runs-api";
import { partFileName } from "./recording-format";
import {
  browserLocks,
  journalLockName,
  RecordingJournal,
  type JournalDegradation,
  type JournalLocks
} from "./recording-journal";
import {
  indexedDbRecordings,
  partKey,
  RECORDING_TTL_MS,
  type ContractSnapshot,
  type JournalMeta,
  type PartAddress,
  type RecordingDatabase,
  type StoredPart
} from "./recording-store";
import { withRecordedDuration } from "./webm-duration";

/**
 * Keeps the recordings of one run form on the device: each finished part as
 * it is handed over, and the part being recorded through its journal. When
 * the form opens again after a closed tab, a reload or a crash (or after
 * "Spara och fortsätt senare"), what was kept is offered to continue: parts
 * the page left mid-recording are rebuilt from their journals first.
 *
 * Every storage access is guarded: without storage, or when it fails, the
 * recording works as before and lives only in this tab, which the form says.
 */

/** A recording kept on the device, as the resume prompt describes it. */
export type SavedRecording = {
  sessionId: string;
  parts: number;
  durationMs: number;
  /** When it began: its first part's start. */
  startedAt: number;
  /** Where audio of a part rebuilt from its journal ends; null when none was. */
  interruptedAt: number | null;
  contract: ContractSnapshot;
};

/** Why a kept recording cannot continue in this form, or null when it can. */
export type ResumeRefusal = "step_changed" | "too_many_parts" | "type_not_accepted";

/** Where a part of this form is kept: on the device, or only in this tab. */
export type PartKeeping = "device" | "tab";

/** What the recorder tells about the parts it records. */
export type RecorderJournal = {
  begin(part: JournalPart): void;
  append(part: JournalPart, chunk: Blob, recordedMs: number): void;
  /** The page goes away mid-part: what was written stays, to be rebuilt. */
  leave(part: JournalPart): void;
  /** Nothing of the part is kept. */
  discard(part: JournalPart): void;
};

export type JournalPart = {
  sessionId: string;
  index: number;
  mimeType: string;
  capturedAt: number;
};

export function contractSnapshot(
  input: Pick<
    RuntimeInput,
    "input_format" | "max_files" | "max_file_size_bytes" | "accepted_mimetypes"
  > | null,
  publishedFlowVersion: number | null
): ContractSnapshot {
  return {
    publishedFlowVersion,
    inputFormat: input?.input_format ?? null,
    maxFiles: input?.max_files ?? null,
    maxFileSizeBytes: input?.max_file_size_bytes ?? null,
    acceptedMimetypes: [...(input?.accepted_mimetypes ?? [])]
  };
}

const essence = (type: string) => type.split(";", 1)[0]?.trim().toLowerCase() ?? "";

function accepts(accepted: readonly string[], type: string): boolean {
  if (accepted.length === 0) return true;
  const own = essence(type);
  return accepted.some((entry) => {
    const allowed = entry.toLowerCase();
    return allowed.endsWith("/*") ? own.startsWith(allowed.slice(0, -1)) : own === allowed;
  });
}

/**
 * Whether a kept recording can be added to the step as it is now: the step
 * must still take audio, have room for every part and accept their type. A
 * new published version or a smaller size limit alone does not refuse it
 * (a part too large is refused at its upload, like any file).
 */
export function resumeRefusal(
  current: ContractSnapshot,
  parts: readonly Pick<StoredPart, "mimeType">[]
): ResumeRefusal | null {
  if (current.inputFormat !== "audio") return "step_changed";
  if (current.maxFiles != null && parts.length > current.maxFiles) return "too_many_parts";
  if (parts.some((part) => !accepts(current.acceptedMimetypes, part.mimeType))) {
    return "type_not_accepted";
  }
  return null;
}

/** A kept part as the file the form uploads. */
export function storedPartFile(part: StoredPart): File {
  return new File(
    [part.blob],
    partFileName(part.sessionId, part.index, part.capturedAt, part.mimeType),
    { type: part.mimeType }
  );
}

/** The device's store where the browser has one. */
export function browserRecordings(): RecordingDatabase | null {
  try {
    return indexedDbRecordings();
  } catch {
    return null;
  }
}

export type ScanResult = {
  saved: SavedRecording[];
  /** Some kept recordings could not be read: not the same as none. */
  incomplete: boolean;
};

export class RecordingKeeper {
  #flowId: string;
  #db: RecordingDatabase | null;
  #locks: JournalLocks | null;
  #now: () => number;
  #journal: RecordingJournal | null;
  /** The recordings this form made or continued, per step. */
  #sessions = new Map<string, Set<string>>();
  /** Recordings forgotten: their late chunks and parts are not kept. */
  #forgotten = new Set<string>();
  #keeping = new Map<string, PartKeeping>();
  #listeners = new Set<() => void>();
  #degraded = new Map<string, JournalDegradation>();
  #version = 0;

  constructor(
    flowId: string,
    db: RecordingDatabase | null = browserRecordings(),
    locks: JournalLocks | null = browserLocks(),
    now: () => number = Date.now
  ) {
    this.#flowId = flowId;
    this.#db = db;
    this.#locks = locks;
    this.#now = now;
    this.#journal = db
      ? new RecordingJournal(db, (reason, address) => this.#degrade(address, reason), locks, now)
      : null;
  }

  /** Whether this browser keeps recordings on the device at all. */
  get available(): boolean {
    return this.#db !== null;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  /** Changes whenever a part's keeping or a journal's state changes. */
  getVersion = (): number => this.#version;

  /** How a step's recording is kept so far: null when nothing degraded it. */
  degradation(stepId: string): JournalDegradation | null {
    return this.#degraded.get(stepId) ?? null;
  }

  /** Where a part handed to `keepPart` is kept; undefined while it is being stored. */
  keeping(stepId: string, sessionId: string, index: number): PartKeeping | undefined {
    return this.#keeping.get(partKey({ flowId: this.#flowId, stepId, sessionId, index }));
  }

  /** The journal a step's recorder writes its parts to. */
  journalFor(stepId: string, contract: () => ContractSnapshot): RecorderJournal {
    const address = (part: JournalPart): PartAddress => ({
      flowId: this.#flowId,
      stepId,
      sessionId: part.sessionId,
      index: part.index
    });
    return {
      begin: (part) => {
        this.#track(stepId, part.sessionId);
        if (!this.#journal) {
          this.#degrade(address(part), "failed");
          return;
        }
        const meta: Omit<JournalMeta, "lastChunkAt"> = {
          ...address(part),
          mimeType: part.mimeType,
          capturedAt: part.capturedAt,
          contract: contract()
        };
        this.#journal.begin(meta);
      },
      append: (part, chunk, recordedMs) => {
        if (this.#isForgotten(stepId, part.sessionId)) return;
        this.#journal?.append(address(part), chunk, recordedMs);
      },
      leave: (part) => {
        if (this.#isForgotten(stepId, part.sessionId)) void this.#journal?.discard(address(part));
        else void this.#journal?.leave(address(part));
      },
      discard: (part) => void this.#journal?.discard(address(part))
    };
  }

  /**
   * Stores a finished part before it uploads, so a reload during the upload
   * still finds it; the part's journal then goes. Resolves with where the
   * part is kept.
   */
  async keepPart(
    stepId: string,
    part: Omit<StoredPart, "flowId" | "stepId" | "interrupted">
  ): Promise<PartKeeping> {
    const address: PartAddress = {
      flowId: this.#flowId,
      stepId,
      sessionId: part.sessionId,
      index: part.index
    };
    this.#track(stepId, part.sessionId);
    let keeping: PartKeeping = "tab";
    if (this.#db && !this.#isForgotten(stepId, part.sessionId)) {
      try {
        await this.#db.putPart({ ...part, ...address, interrupted: false });
        keeping = "device";
      } catch {
        keeping = "tab";
      }
    }
    // A part only this tab holds keeps its journal, to rebuild it after a reload.
    if (keeping === "device") await this.#journal?.commit(address);
    if (this.#isForgotten(stepId, part.sessionId)) {
      await this.#db?.deletePart(address).catch(() => undefined);
      return "tab";
    }
    this.#keeping.set(partKey(address), keeping);
    this.#changed();
    return keeping;
  }

  /** A part taken off the form: nor is it offered again after a reload. */
  async forgetPart(stepId: string, sessionId: string, index: number): Promise<void> {
    const address: PartAddress = { flowId: this.#flowId, stepId, sessionId, index };
    this.#keeping.delete(partKey(address));
    this.#changed();
    try {
      await this.#db?.deletePart(address);
    } catch {
      // Offered again after a reload, where it can be discarded.
    }
  }

  /** A recording thrown away, or taken by a started run: nothing of it stays. */
  async forgetSession(stepId: string, sessionId: string): Promise<boolean> {
    const key = `${stepId}::${sessionId}`;
    this.#forgotten.add(key);
    await this.#journal?.discardSession(this.#flowId, stepId, sessionId);
    try {
      await this.#db?.deleteSession(this.#flowId, stepId, sessionId);
      return true;
    } catch {
      // Still stored: it can be discarded again, or continued after all.
      this.#forgotten.delete(key);
      return false;
    }
  }

  /** Every recording this form made or continued is forgotten. */
  async forgetAll(): Promise<void> {
    const sessions = [...this.#sessions.entries()].flatMap(([stepId, ids]) =>
      [...ids].map((sessionId) => [stepId, sessionId] as const)
    );
    await Promise.all(sessions.map(([stepId, sessionId]) => this.forgetSession(stepId, sessionId)));
  }

  /** Whether this form made or continued any recording. */
  get holdsSessions(): boolean {
    return [...this.#sessions.values()].some((ids) => ids.size > 0);
  }

  /**
   * The recordings kept for a step, newest first, after parts the page left
   * mid-recording are rebuilt from their journals. Recordings with no
   * activity for a day are deleted.
   */
  async scan(stepId: string): Promise<ScanResult> {
    const db = this.#db;
    if (!db) return { saved: [], incomplete: false };
    let incomplete = false;
    try {
      incomplete = !(await this.#recoverJournals(db, stepId));
    } catch {
      incomplete = true;
    }
    let parts: StoredPart[];
    try {
      parts = await db.listParts(this.#flowId, stepId);
    } catch {
      return { saved: [], incomplete: true };
    }
    const bySession = new Map<string, StoredPart[]>();
    for (const part of parts) {
      const list = bySession.get(part.sessionId);
      if (list) list.push(part);
      else bySession.set(part.sessionId, [part]);
    }
    const saved: SavedRecording[] = [];
    const cutoff = this.#now() - RECORDING_TTL_MS;
    for (const [sessionId, list] of bySession) {
      const lastActivity = Math.max(...list.map((part) => part.capturedAt + part.durationMs));
      if (lastActivity < cutoff) {
        await db.deleteSession(this.#flowId, stepId, sessionId).catch(() => undefined);
        continue;
      }
      const interrupted = list.filter((part) => part.interrupted);
      saved.push({
        sessionId,
        parts: list.length,
        durationMs: list.reduce((sum, part) => sum + part.durationMs, 0),
        startedAt: Math.min(...list.map((part) => part.capturedAt)),
        interruptedAt:
          interrupted.length > 0
            ? Math.max(...interrupted.map((part) => part.capturedAt + part.durationMs))
            : null,
        contract: list[0]!.contract
      });
    }
    saved.sort((a, b) => b.startedAt - a.startedAt);
    return { saved, incomplete };
  }

  /** A kept recording's parts, in order; rejects when they could not be read. */
  async readSession(stepId: string, sessionId: string): Promise<StoredPart[]> {
    if (!this.#db) return [];
    const parts = await this.#db.listParts(this.#flowId, stepId);
    return parts.filter((part) => part.sessionId === sessionId).sort((a, b) => a.index - b.index);
  }

  /** A kept recording goes on in this form: its parts count as kept on the device. */
  adopt(stepId: string, parts: readonly StoredPart[]): void {
    for (const part of parts) {
      this.#track(stepId, part.sessionId);
      this.#keeping.set(partKey(part), "device");
    }
    this.#changed();
  }

  /**
   * Journals with no stored part become their recording's parts, under a
   * lock per step so two tabs never rebuild the same part; a journal whose
   * part another tab still records holds its lock and is left alone. False
   * when a part could not be rebuilt (the journal stays for another try).
   */
  async #recoverJournals(db: RecordingDatabase, stepId: string): Promise<boolean> {
    const locks = this.#locks;
    // Without Web Locks nothing was journaled.
    if (!locks) return true;
    return locks.request(`eneo-flow-recovery:${this.#flowId}::${stepId}`, async () => {
      let complete = true;
      const journals = await db.listJournals(this.#flowId, stepId);
      for (const meta of journals) {
        await locks.request(journalLockName(meta), { ifAvailable: true }, async (lock) => {
          if (!lock) return;
          complete = (await this.#recoverJournal(db, meta)) && complete;
        });
      }
      return complete;
    });
  }

  async #recoverJournal(db: RecordingDatabase, meta: JournalMeta): Promise<boolean> {
    const stored = await db.hasPart(meta);
    // Slow to read is not gone: nothing is replaced or dropped until an answer comes.
    if (stored === null) return false;
    const expired = meta.lastChunkAt < this.#now() - RECORDING_TTL_MS;
    if (!stored && !expired) {
      const chunks = await db.readChunks(meta);
      if (chunks === null) return false;
      const [first, ...rest] = chunks;
      if (first) {
        const durationMs = Math.max(0, chunks.at(-1)!.recordedMs);
        let head: Blob = first.blob;
        try {
          head = await withRecordedDuration(first.blob, durationMs, meta.mimeType);
        } catch {
          // The header stays as recorded: players then guess the length.
        }
        try {
          await db.putPart({
            flowId: meta.flowId,
            stepId: meta.stepId,
            sessionId: meta.sessionId,
            index: meta.index,
            blob: new Blob([head, ...rest.map((chunk) => chunk.blob)], { type: meta.mimeType }),
            mimeType: meta.mimeType,
            durationMs,
            capturedAt: meta.capturedAt,
            interrupted: true,
            contract: meta.contract
          });
        } catch {
          return false;
        }
      }
    }
    await db.dropJournal(meta).catch(() => undefined);
    return true;
  }

  #track(stepId: string, sessionId: string) {
    const ids = this.#sessions.get(stepId) ?? new Set<string>();
    ids.add(sessionId);
    this.#sessions.set(stepId, ids);
  }

  #isForgotten(stepId: string, sessionId: string): boolean {
    return this.#forgotten.has(`${stepId}::${sessionId}`);
  }

  #degrade(address: PartAddress, reason: JournalDegradation) {
    const current = this.#degraded.get(address.stepId);
    // "failed" says more than "unavailable": it is kept once seen.
    if (current === "failed" || current === reason) return;
    this.#degraded.set(address.stepId, reason);
    this.#changed();
  }

  #changed() {
    this.#version += 1;
    for (const listener of this.#listeners) listener();
  }
}
