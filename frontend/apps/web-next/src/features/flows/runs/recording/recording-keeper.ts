import { withRecordedDuration } from "@/lib/audio/webm-duration";
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

/**
 * Keeps the recordings of one run form on the device: each finished part as
 * it is handed over, and the part being recorded through its journal. When
 * the form opens again after a closed tab, a reload or a crash (or after
 * "Spara och fortsätt senare"), what was kept is offered to continue: parts
 * the page left mid-recording are rebuilt from their journals first.
 *
 * Every storage access is guarded: without storage, or when it fails, the
 * recording works as before and lives only in this tab, which the form says.
 *
 * The device's store is shared by everyone who signs in on this browser, so
 * each part and journal carries who recorded it, and a form offers, reads
 * and rebuilds only the signed-in person's own; without their id, nothing.
 * That is a choice of what to offer, not a protection against someone who
 * reads the browser's storage directly. Recordings with no activity for a
 * day are deleted whoever made them.
 *
 * A kept recording has at most one holder: the form that records it or has
 * continued it. The keeper holds a Web Lock per recording for that form, and
 * only the holder writes the recording to the device, continues it or
 * discards it; another tab's part stays in that tab. The browser lets go of
 * the lock when the tab closes, crashes or reloads. Without Web Locks there
 * is no holder, and recordings are kept as before.
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

/**
 * Why a kept recording cannot continue in this form: the step no longer
 * takes it, another form holds it ("open_elsewhere"), or it could not be
 * read or held ("read_failed").
 */
export type ResumeRefusal =
  "step_changed" | "too_many_parts" | "type_not_accepted" | "open_elsewhere" | "read_failed";

/**
 * How "Fortsätt" on a kept recording went: its parts are this form's now,
 * it was refused, nothing of it was left, a press was already under way
 * ("busy"), or the form went meanwhile ("closed").
 */
export type ResumeOutcome =
  | { kind: "continued"; parts: StoredPart[] }
  | { kind: "refused"; refusal: ResumeRefusal }
  | { kind: "empty" }
  | { kind: "busy" }
  | { kind: "closed" };

/**
 * How discarding a kept recording from the resume prompt went: refused while
 * another form holds it ("open_elsewhere") or when the browser refused to ask
 * ("read_failed"); "closed" when the form went meanwhile.
 */
export type DiscardOutcome =
  "discarded" | "discard_failed" | "open_elsewhere" | "read_failed" | "closed";

/** Where a part of this form is kept: on the device, or only in this tab. */
export type PartKeeping = "device" | "tab";

/**
 * The answer to the keeper asking to hold a recording: "taken" while another
 * form holds it, "failed" when the browser refused the request, "closed" once
 * the form let go.
 */
type HoldAnswer = "held" | "taken" | "failed" | "closed";

type Hold = {
  stepId: string;
  sessionId: string;
  answer: Promise<HoldAnswer>;
  state: "asking" | "held" | "refused" | "released";
  /** Letting go: no new write is let in, the ones under way end first. */
  closing: Promise<void> | null;
  letGo: () => void;
};

/** The lock a form holds while it has a recording. */
function holdLockName(flowId: string, stepId: string, sessionId: string): string {
  return `eneo-flow-recording-holder:${flowId}::${stepId}::${sessionId}`;
}

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

/** The page's storage managers already asked to keep their storage: one per page. */
const storageAsked = new WeakSet<object>();

export class RecordingKeeper {
  #flowId: string;
  #userId: string | null;
  #db: RecordingDatabase | null;
  #locks: JournalLocks | null;
  #now: () => number;
  #journal: RecordingJournal | null;
  /** The recordings this form made or continued, per step. */
  #sessions = new Map<string, Set<string>>();
  /** Recordings forgotten: their late chunks and parts are not kept. */
  #forgotten = new Set<string>();
  #keeping = new Map<string, PartKeeping>();
  /** Each part handed to `keepPart`, by its key, until it is stored or not. */
  #storing = new Map<string, Promise<PartKeeping>>();
  #listeners = new Set<() => void>();
  #degraded = new Map<string, JournalDegradation>();
  #version = 0;
  /** What this keeper holds, asked to hold or was refused, per recording: it never refuses itself. */
  #holds = new Map<string, Hold>();
  /** Writes and removals under way, per recording, which end before its hold is let go. */
  #work = new Map<string, Set<Promise<unknown>>>();
  /** The form let go: nothing more is held or written. */
  #closed = false;
  /** Recordings whose "Fortsätt" is under way: a second press continues none. */
  #resuming = new Set<string>();

  /** `userId`: the signed-in person, whose recordings are kept and offered; null while not known. */
  constructor(
    flowId: string,
    userId: string | null,
    db: RecordingDatabase | null = browserRecordings(),
    locks: JournalLocks | null = browserLocks(),
    now: () => number = Date.now
  ) {
    this.#flowId = flowId;
    this.#userId = userId;
    this.#db = db;
    this.#locks = locks;
    this.#now = now;
    this.#journal = db
      ? new RecordingJournal(db, (reason, address) => this.#degrade(address, reason), locks, now)
      : null;
  }

  /**
   * Asks the browser, once per page, to keep this site's storage: otherwise
   * it may clear it after days without a visit or when space runs short,
   * and a kept recording with it. The answer is not waited for nor told;
   * without the API, or refused, recordings are kept as before.
   */
  askToKeepStorage(): void {
    if (!this.#db) return;
    try {
      const storage = (typeof navigator === "undefined" ? undefined : navigator.storage) as
        Partial<StorageManager> | undefined;
      if (!storage || storageAsked.has(storage)) return;
      storageAsked.add(storage);
      void storage.persist?.().catch(() => undefined);
    } catch {
      // No storage manager here: recordings are kept as before.
    }
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

  /** The journal a step's recorder writes its parts to; `streamed` as of the part's start. */
  journalFor(
    stepId: string,
    contract: () => ContractSnapshot,
    streamed: () => boolean
  ): RecorderJournal {
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
        // A part begins: the recording's hold is taken, or asked for again after a refusal.
        // Without it the part stays in this tab, as when storage refuses it.
        const held = this.#take(stepId, part.sessionId, { again: true }).then(
          (answer) => answer === "held"
        );
        void held.then((ok) => {
          if (!ok) this.#degrade(address(part), "failed");
        });
        const meta: Omit<JournalMeta, "lastChunkAt"> = {
          ...address(part),
          mimeType: part.mimeType,
          capturedAt: part.capturedAt,
          contract: contract(),
          streamed: streamed(),
          ...this.#owner()
        };
        this.#journal.begin(meta, held);
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
  keepPart(
    stepId: string,
    part: Omit<StoredPart, "flowId" | "stepId" | "interrupted" | "liveTranscript" | "userId">
  ): Promise<PartKeeping> {
    const storing = this.#during(stepId, part.sessionId, this.#store(stepId, part));
    this.#storing.set(
      partKey({ flowId: this.#flowId, stepId, sessionId: part.sessionId, index: part.index }),
      storing
    );
    return storing;
  }

  /**
   * Keeps the core's stored live transcript with the recorded parts it stands
   * for, in order, once they are stored: a reload then still finds it. None
   * of them keeps it when one is not on the device.
   */
  keepLiveTranscript(
    stepId: string,
    parts: readonly Pick<PartAddress, "sessionId" | "index">[],
    id: string
  ): Promise<void> {
    const writing = this.#keepLiveTranscript(stepId, parts, id);
    for (const sessionId of new Set(parts.map((part) => part.sessionId))) {
      this.#during(stepId, sessionId, writing);
    }
    return writing;
  }

  async #keepLiveTranscript(
    stepId: string,
    parts: readonly Pick<PartAddress, "sessionId" | "index">[],
    id: string
  ): Promise<void> {
    const addresses = parts.map((part) => ({ flowId: this.#flowId, stepId, ...part }));
    await Promise.all(addresses.map((address) => this.#storing.get(partKey(address))));
    if (!this.#db || addresses.some((address) => this.#isForgotten(stepId, address.sessionId))) {
      return;
    }
    const held = await Promise.all(addresses.map((address) => this.#holding(address)));
    if (held.includes(false)) return;
    try {
      await this.#db.setLiveTranscript(addresses, { id, parts: addresses.length });
    } catch {
      // A run started after a reload then has no live text for these parts, and says so.
    }
  }

  async #store(
    stepId: string,
    part: Omit<StoredPart, "flowId" | "stepId" | "interrupted" | "liveTranscript" | "userId">
  ): Promise<PartKeeping> {
    const address: PartAddress = {
      flowId: this.#flowId,
      stepId,
      sessionId: part.sessionId,
      index: part.index
    };
    this.#track(stepId, part.sessionId);
    // The hold its part's start took or was refused; asked for only when there was none.
    const held =
      this.#db !== null &&
      !this.#isForgotten(stepId, part.sessionId) &&
      (await this.#take(stepId, part.sessionId)) === "held";
    let keeping: PartKeeping = "tab";
    if (held) {
      try {
        await this.#db!.putPart({ ...part, ...address, interrupted: false, ...this.#owner() });
        keeping = "device";
      } catch {
        keeping = "tab";
      }
    }
    // A part only this tab holds keeps its journal, to rebuild it after a reload; without the
    // hold the journal wrote nothing, and the part ends there.
    if (keeping === "device") await this.#journal?.commit(address);
    else if (!held) await this.#journal?.discard(address);
    if (this.#isForgotten(stepId, part.sessionId)) {
      if (keeping === "device") await this.#db?.deletePart(address).catch(() => undefined);
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
    await this.#during(stepId, sessionId, this.#deletePart(address));
  }

  async #deletePart(address: PartAddress): Promise<void> {
    if (!(await this.#holding(address))) return;
    try {
      await this.#db?.deletePart(address);
    } catch {
      // Offered again after a reload, where it can be discarded.
    }
  }

  /**
   * A recording thrown away, or taken by a started run: nothing of it stays.
   * Only its holder removes anything; one this form never held is left on
   * the device as it is. The hold is let go once the removal has ended,
   * also when it failed.
   */
  async forgetSession(stepId: string, sessionId: string): Promise<boolean> {
    const key = `${stepId}::${sessionId}`;
    this.#forgotten.add(key);
    const removed = await this.#during(stepId, sessionId, this.#deleteSession(stepId, sessionId));
    // Still stored: it can be discarded again, or continued after all.
    if (!removed) this.#forgotten.delete(key);
    await this.#release(stepId, sessionId);
    return removed;
  }

  async #deleteSession(stepId: string, sessionId: string): Promise<boolean> {
    const held = await this.#holding({ stepId, sessionId });
    await this.#journal?.discardSession(this.#flowId, stepId, sessionId);
    if (!held) return true;
    try {
      await this.#db?.deleteSession(this.#flowId, stepId, sessionId);
      return true;
    } catch {
      return false;
    }
  }

  /** A kept recording discarded from the resume prompt: only by its holder, which this form becomes. */
  async discard(stepId: string, sessionId: string): Promise<DiscardOutcome> {
    const answer = await this.#take(stepId, sessionId, { again: true });
    if (answer === "taken") return "open_elsewhere";
    if (answer === "failed") return "read_failed";
    if (answer === "closed") return "closed";
    return (await this.forgetSession(stepId, sessionId)) ? "discarded" : "discard_failed";
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

  /** The form has the keeper (again, after strict mode's first unmount); answers how it lets go. */
  open(): () => void {
    this.#closed = false;
    return () => void this.close();
  }

  /**
   * The form goes: every recording it holds is let go once the writes and
   * removals under way have ended (a run started or a closed form begins
   * those without waiting). Nothing more is held or written.
   */
  async close(): Promise<void> {
    this.#closed = true;
    await Promise.all(
      [...this.#holds.values()].map((hold) => this.#release(hold.stepId, hold.sessionId))
    );
  }

  /**
   * The signed-in person's recordings kept for a step, newest first, after
   * parts they left mid-recording are rebuilt from their journals.
   * Recordings with no activity for a day (their latest part or journal
   * chunk) are deleted, whoever made them; none while journals cannot be read.
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
    // A journal is activity too: a recording continued just before its day ran out goes on.
    let journals: JournalMeta[] | null = null;
    try {
      journals = await db.listJournals(this.#flowId, stepId);
    } catch {
      incomplete = true;
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
      const lastActivity = Math.max(
        ...list.map((part) => part.capturedAt + part.durationMs),
        ...(journals ?? [])
          .filter((meta) => meta.sessionId === sessionId)
          .map((meta) => meta.lastChunkAt)
      );
      if (lastActivity < cutoff) {
        // Unread journals are not "no journal": nothing is deleted until they can be read.
        if (journals) {
          await db.deleteSession(this.#flowId, stepId, sessionId).catch(() => undefined);
        }
        continue;
      }
      const own = list.filter(this.#mine);
      if (own.length === 0) continue;
      const interrupted = own.filter((part) => part.interrupted);
      saved.push({
        sessionId,
        parts: own.length,
        durationMs: own.reduce((sum, part) => sum + part.durationMs, 0),
        startedAt: Math.min(...own.map((part) => part.capturedAt)),
        interruptedAt:
          interrupted.length > 0
            ? Math.max(...interrupted.map((part) => part.capturedAt + part.durationMs))
            : null,
        contract: own[0]!.contract
      });
    }
    saved.sort((a, b) => b.startedAt - a.startedAt);
    return { saved, incomplete };
  }

  /** The signed-in person's kept recording's parts, in order; rejects when they could not be read. */
  async readSession(stepId: string, sessionId: string): Promise<StoredPart[]> {
    if (!this.#db) return [];
    const parts = await this.#db.listParts(this.#flowId, stepId);
    return parts
      .filter((part) => part.sessionId === sessionId && this.#mine(part))
      .sort((a, b) => a.index - b.index);
  }

  /**
   * "Fortsätt": a kept recording goes on in this form, which holds it from
   * now on. Refused while another form holds it; otherwise its parts are
   * read and the step tried (`resumeRefusal`) before they count as this
   * form's. A hold taken here that leads to no takeover is let go.
   */
  async resume(
    stepId: string,
    sessionId: string,
    contract: ContractSnapshot
  ): Promise<ResumeOutcome> {
    const key = `${stepId}::${sessionId}`;
    if (this.#resuming.has(key)) return { kind: "busy" };
    this.#resuming.add(key);
    try {
      const heldBefore = this.#holds.get(key)?.state === "held";
      const answer = await this.#take(stepId, sessionId, { again: true });
      if (answer === "taken") return { kind: "refused", refusal: "open_elsewhere" };
      if (answer === "failed") return { kind: "refused", refusal: "read_failed" };
      if (answer === "closed") return { kind: "closed" };
      const outcome = await this.#takeOver(stepId, sessionId, contract);
      if (outcome.kind !== "continued" && !heldBefore) await this.#release(stepId, sessionId);
      return outcome;
    } finally {
      this.#resuming.delete(key);
    }
  }

  async #takeOver(
    stepId: string,
    sessionId: string,
    contract: ContractSnapshot
  ): Promise<ResumeOutcome> {
    let parts: StoredPart[];
    try {
      parts = await this.readSession(stepId, sessionId);
    } catch {
      return { kind: "refused", refusal: "read_failed" };
    }
    if (this.#closed) return { kind: "closed" };
    if (parts.length === 0) return { kind: "empty" };
    // The flow may have changed since: its step must still take these parts as they are.
    const refusal = resumeRefusal(contract, parts);
    if (refusal) return { kind: "refused", refusal };
    this.#adopt(stepId, parts);
    return { kind: "continued", parts };
  }

  /** A kept recording goes on in this form: its parts count as kept on the device. */
  #adopt(stepId: string, parts: readonly StoredPart[]): void {
    for (const part of parts) {
      this.#track(stepId, part.sessionId);
      this.#keeping.set(partKey(part), "device");
    }
    this.#changed();
  }

  /**
   * The signed-in person's journals with no stored part become their
   * recording's parts, under a lock per step so two tabs never rebuild the
   * same part; a journal whose part another tab still records holds its lock
   * and is left alone, as is another person's until it expires. False when a
   * part could not be rebuilt (the journal stays for another try).
   */
  async #recoverJournals(db: RecordingDatabase, stepId: string): Promise<boolean> {
    const locks = this.#locks;
    // Without Web Locks nothing was journaled.
    if (!locks) return true;
    return locks.request(`eneo-flow-recovery:${this.#flowId}::${stepId}`, async () => {
      let complete = true;
      const journals = await db.listJournals(this.#flowId, stepId);
      const cutoff = this.#now() - RECORDING_TTL_MS;
      for (const meta of journals) {
        if (!this.#mine(meta) && meta.lastChunkAt >= cutoff) continue;
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
            contract: meta.contract,
            streamed: meta.streamed,
            ...(meta.userId === undefined ? {} : { userId: meta.userId })
          });
        } catch {
          return false;
        }
      }
    }
    await db.dropJournal(meta).catch(() => undefined);
    return true;
  }

  /**
   * Asks to hold a recording, without waiting for another form: answered from
   * this keeper's own book when it holds the recording, asks for it or was
   * refused it (`again` asks anew after a refusal). A hold granted after the
   * form let go is let go at once. Without Web Locks nothing is held, and
   * every write goes ahead as before.
   */
  #take(stepId: string, sessionId: string, { again = false } = {}): Promise<HoldAnswer> {
    const locks = this.#locks;
    if (!locks) return Promise.resolve("held");
    const key = `${stepId}::${sessionId}`;
    const current = this.#holds.get(key);
    if (this.#closed || current?.closing) return Promise.resolve("closed");
    if (current?.state === "asking" || current?.state === "held") return current.answer;
    if (current?.state === "refused" && !again) return current.answer;
    if (current?.state === "released" && !again) return Promise.resolve("closed");
    const hold: Hold = {
      stepId,
      sessionId,
      answer: Promise.resolve("failed"),
      state: "asking",
      closing: null,
      letGo: () => {
        hold.state = "released";
      }
    };
    hold.answer = new Promise<HoldAnswer>((resolve) => {
      const answer = (value: HoldAnswer) => {
        if (hold.state === "asking") hold.state = value === "held" ? "held" : "refused";
        resolve(value);
      };
      try {
        locks
          .request(holdLockName(this.#flowId, stepId, sessionId), { ifAvailable: true }, (lock) => {
            if (!lock) {
              answer("taken");
              return;
            }
            if (hold.closing || hold.state !== "asking") {
              answer("closed");
              return;
            }
            return new Promise<void>((release) => {
              hold.letGo = () => {
                hold.state = "released";
                release();
              };
              answer("held");
            });
          })
          .catch(() => answer("failed"));
      } catch {
        answer("failed");
      }
    });
    this.#holds.set(key, hold);
    return hold.answer;
  }

  /** Whether this keeper holds the recording now, for a write that needs it; never once it lets go. */
  async #holding({ stepId, sessionId }: Pick<PartAddress, "stepId" | "sessionId">) {
    if (!this.#locks) return true;
    const hold = this.#holds.get(`${stepId}::${sessionId}`);
    if (!hold || hold.closing || hold.state === "released" || this.#closed) return false;
    return (await hold.answer) === "held";
  }

  /** A write or removal for a recording, which its hold outlasts. */
  #during<T>(stepId: string, sessionId: string, work: Promise<T>): Promise<T> {
    const key = `${stepId}::${sessionId}`;
    const pending = this.#work.get(key) ?? new Set<Promise<unknown>>();
    this.#work.set(key, pending);
    pending.add(work);
    const done = () => pending.delete(work);
    work.then(done, done);
    return work;
  }

  /**
   * Lets go of a recording: no new write is let in, the part being recorded
   * leaves its journal as it is, and the writes and removals under way end
   * (successful or not) before the lock goes.
   */
  #release(stepId: string, sessionId: string): Promise<void> {
    const hold = this.#holds.get(`${stepId}::${sessionId}`);
    if (!hold || hold.state === "released") return Promise.resolve();
    hold.closing ??= (async () => {
      await this.#journal?.leaveSession(this.#flowId, stepId, sessionId);
      const pending = this.#work.get(`${stepId}::${sessionId}`);
      while (pending && pending.size > 0) await Promise.allSettled([...pending]);
      hold.letGo();
      hold.closing = null;
    })();
    return hold.closing;
  }

  /** Whether the signed-in person recorded it; never while their id is not known. */
  #mine = (row: { userId?: string }): boolean =>
    this.#userId !== null && row.userId === this.#userId;

  /** Who records what this form keeps, as each part and journal carries it. */
  #owner(): { userId?: string } {
    return this.#userId === null ? {} : { userId: this.#userId };
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
