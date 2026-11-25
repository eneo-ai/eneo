/**
 * Loss catalogue, cleanup group: what the base's keeper, journal and store
 * leave on the device when a scan's age cleanup and its journal recovery
 * meet a recording that a tab is writing, has paused or has continued.
 * Each test states what the base does today, with exact keys and bytes;
 * "base loses" marks audio a fix must keep, "base keeps" what no fix may lose.
 * Two tabs are two keepers on one store, one lock manager and one clock.
 */
import { describe, expect, it } from "vitest";
import { journalLockName } from "../recording-journal";
import { RecordingKeeper, type JournalPart } from "../recording-keeper";
import {
  memoryRecordings,
  partKey,
  RECORDING_TTL_MS,
  type ContractSnapshot,
  type JournalMeta,
  type StoredPart
} from "../recording-store";
import { fakeLocks } from "./catalog-locks";

const CONTRACT: ContractSnapshot = {
  publishedFlowVersion: 4,
  inputFormat: "audio",
  maxFiles: 10,
  maxFileSizeBytes: 10_000_000,
  acceptedMimetypes: ["audio/webm", "audio/mp4"]
};
const WEBM = "audio/webm;codecs=opus";
const MP4 = "audio/mp4";
const HOUR = 3_600_000;
const T0 = Date.UTC(2026, 10, 25, 12, 0, 0);
const KEY = (sessionId: string, index: number) => partKey(addr(sessionId, index));

type Db = ReturnType<typeof memoryRecordings>;

function addr(sessionId: string, index: number) {
  return { flowId: "flow-1", stepId: "step-1", sessionId, index };
}

function setup({ locks = true } = {}) {
  const db = memoryRecordings();
  const lockManager = fakeLocks();
  let now = T0;
  /** One form, in one tab, of the same signed-in person. */
  const tab = (userId: string | null = "user-a") =>
    new RecordingKeeper("flow-1", userId, db, locks ? lockManager.locks : null, () => now);
  return {
    db,
    lockManager,
    tab,
    now: () => now,
    at: (time: number) => {
      now = time;
    }
  };
}

/** Lets queued journal writes and lock grants land. */
async function flush(rounds = 4) {
  for (let i = 0; i < rounds; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
}

/** Everything on the device: each part's and chunk's bytes by key, and the journals' keys. */
async function device(db: Db) {
  const text = async <T extends { blob: Blob }>(map: Map<string, T>) =>
    Object.fromEntries(
      await Promise.all([...map.entries()].sort().map(async ([k, v]) => [k, await v.blob.text()]))
    );
  return {
    parts: await text(db.parts),
    journals: [...db.journals.keys()].sort(),
    chunks: await text(db.chunks)
  };
}

function seedPart(db: Db, sessionId: string, index: number, capturedAt: number, body: string) {
  return db.putPart({
    ...addr(sessionId, index),
    blob: new Blob([body], { type: WEBM }),
    mimeType: WEBM,
    durationMs: 60_000,
    capturedAt,
    interrupted: false,
    contract: CONTRACT,
    streamed: false,
    userId: "user-a"
  } satisfies StoredPart);
}

/** A journal a page left: `count` one-second chunks "c0".."c{n}", the last written at `lastAt`. */
async function seedJournal(
  db: Db,
  sessionId: string,
  index: number,
  capturedAt: number,
  count: number,
  lastAt: number,
  userId: string | null = "user-a"
) {
  await db.putJournal({
    ...addr(sessionId, index),
    mimeType: WEBM,
    capturedAt,
    contract: CONTRACT,
    streamed: false,
    lastChunkAt: capturedAt,
    ...(userId === null ? {} : { userId })
  } satisfies JournalMeta);
  for (let seq = 0; seq < count; seq += 1) {
    await db.appendChunk(addr(sessionId, index), seq, {
      blob: new Blob([`c${seq}`], { type: WEBM }),
      recordedMs: (seq + 1) * 1_000,
      at: seq === count - 1 ? lastAt : capturedAt + (seq + 1) * 1_000
    });
  }
}

const SIX_CHUNKS = (sessionId: string, index: number) =>
  Object.fromEntries(
    [0, 1, 2, 3, 4, 5].map((seq) => [
      `${KEY(sessionId, index)}::${String(seq).padStart(6, "0")}`,
      `c${seq}`
    ])
  );

/** A part the recorder records, as it tells the journal. */
const recorded = (index: number, capturedAt: number, mimeType = WEBM): JournalPart => ({
  sessionId: "rec-1",
  index,
  mimeType,
  capturedAt
});

const finished = (index: number, body: string, capturedAt: number, mimeType = WEBM) => ({
  sessionId: "rec-1",
  index,
  blob: new Blob([body], { type: mimeType }),
  mimeType,
  durationMs: 10_000,
  capturedAt,
  contract: CONTRACT,
  streamed: false
});

describe("loss catalogue: cleanup", () => {
  // review finding F10 (plan review; base-vs-head F10): a fix must count the wall-clock time of the last chunk, so a long-paused part is rebuilt and offered.
  it("base loses: a part paused long after it began is rebuilt with its start as its activity and deleted at once", async () => {
    const { db, tab, at } = setup();
    const now = T0 + 2 * RECORDING_TTL_MS;
    at(now);
    await seedJournal(db, "rec-1", 0, now - RECORDING_TTL_MS - 60_000, 6, now - 1_000);
    expect(await device(db)).toEqual({
      parts: {},
      journals: [KEY("rec-1", 0)],
      chunks: SIX_CHUNKS("rec-1", 0)
    });

    const result = await tab().scan("step-1");

    expect(result).toEqual({ saved: [], incomplete: false });
    expect(await device(db)).toEqual({ parts: {}, journals: [], chunks: {} });
  });

  // review finding F10 control (base-vs-head F10 control): a fix must keep rebuilding a part within its day with exactly these bytes and length.
  it("base keeps: a part left within its day is rebuilt from its chunks and offered", async () => {
    const { db, tab, at } = setup();
    const now = T0 + 2 * RECORDING_TTL_MS;
    at(now);
    const capturedAt = now - 23 * HOUR;
    await seedJournal(db, "rec-1", 0, capturedAt, 6, now - 1_000);

    const result = await tab().scan("step-1");

    expect(await device(db)).toEqual({
      parts: { [KEY("rec-1", 0)]: "c0c1c2c3c4c5" },
      journals: [],
      chunks: {}
    });
    expect(db.parts.get(KEY("rec-1", 0))).toMatchObject({
      interrupted: true,
      durationMs: 6_000,
      capturedAt
    });
    expect(result.saved).toEqual([
      expect.objectContaining({ sessionId: "rec-1", parts: 1, durationMs: 6_000 })
    ]);
  });

  // review finding base-vs-head F10b: a fix must keep an old part and a fresh journal another tab holds, untouched, while that tab holds it.
  it("base keeps: an old part and a fresh journal that another tab holds stay and are offered", async () => {
    const { db, tab, at, lockManager } = setup();
    const now = T0 + 2 * RECORDING_TTL_MS;
    at(now);
    await seedPart(db, "rec-1", 0, now - RECORDING_TTL_MS - HOUR, "part0");
    await seedJournal(db, "rec-1", 1, now - RECORDING_TTL_MS - 60_000, 6, now - 1_000);
    lockManager.holdElsewhere(journalLockName(addr("rec-1", 1)));

    const result = await tab().scan("step-1");

    expect(await device(db)).toEqual({
      parts: { [KEY("rec-1", 0)]: "part0" },
      journals: [KEY("rec-1", 1)],
      chunks: SIX_CHUNKS("rec-1", 1)
    });
    expect(result.saved).toEqual([expect.objectContaining({ sessionId: "rec-1", parts: 1 })]);
  });

  // review finding F10 with base-vs-head F10b: a fix must keep both parts once the holding tab lets go, since the last chunk is one second old.
  it("base loses: once the tab holding a long-paused last part lets go, the next scan deletes the whole recording", async () => {
    const { db, tab, at, lockManager } = setup();
    const now = T0 + 2 * RECORDING_TTL_MS;
    at(now);
    await seedPart(db, "rec-1", 0, now - RECORDING_TTL_MS - HOUR, "part0");
    await seedJournal(db, "rec-1", 1, now - RECORDING_TTL_MS - 60_000, 6, now - 1_000);
    const lock = journalLockName(addr("rec-1", 1));
    lockManager.holdElsewhere(lock);
    await tab().scan("step-1");
    lockManager.releaseElsewhere(lock);

    const result = await tab().scan("step-1");

    expect(result).toEqual({ saved: [], incomplete: false });
    expect(await device(db)).toEqual({ parts: {}, journals: [], chunks: {} });
  });

  // review finding base-vs-head F10c: a fix must let a journal kept without an owner be rebuilt or offered before it ages out, not leave it unreachable.
  it("base loses: a fresh journal without an owner is never rebuilt and is deleted once a day has passed", async () => {
    const { db, tab, at } = setup();
    const now = T0 + 2 * RECORDING_TTL_MS;
    at(now);
    await seedJournal(db, "rec-1", 0, now - 10 * 60_000, 6, now - 1_000, null);

    const first = await tab().scan("step-1");

    expect(first).toEqual({ saved: [], incomplete: false });
    expect(await device(db)).toEqual({
      parts: {},
      journals: [KEY("rec-1", 0)],
      chunks: SIX_CHUNKS("rec-1", 0)
    });

    at(now + RECORDING_TTL_MS);
    const dayLater = await tab().scan("step-1");

    expect(dayLater).toEqual({ saved: [], incomplete: false });
    expect(await device(db)).toEqual({ parts: {}, journals: [], chunks: {} });
  });

  // base-vs-head section 5 (parts kept without userId are no longer offered): a fix must let a part kept without an owner be reached before it ages out, not leave it unreachable.
  it("base loses: a fresh part kept without an owner is never offered and is deleted once a day has passed", async () => {
    const { db, tab, at } = setup();
    const now = T0 + 2 * RECORDING_TTL_MS;
    at(now);
    const { userId: _owner, ...ownerless } = {
      ...addr("rec-1", 0),
      blob: new Blob(["part0"], { type: WEBM }),
      mimeType: WEBM,
      durationMs: 60_000,
      capturedAt: now - HOUR,
      interrupted: false,
      contract: CONTRACT,
      streamed: false,
      userId: "user-a"
    } satisfies StoredPart;
    await db.putPart(ownerless);

    expect(await tab().scan("step-1")).toEqual({ saved: [], incomplete: false });
    expect(await device(db)).toEqual({
      parts: { [KEY("rec-1", 0)]: "part0" },
      journals: [],
      chunks: {}
    });

    at(now + RECORDING_TTL_MS);
    expect(await tab().scan("step-1")).toEqual({ saved: [], incomplete: false });
    expect(await device(db)).toEqual({ parts: {}, journals: [], chunks: {} });
  });

  // review finding F11 (plan review; base-vs-head F11): a fix must re-read the journal under its lock and keep it, with the fresh chunk, when a chunk came after the listing.
  it("base loses: recovery deletes a journal that looked expired when listed, with the fresh chunk written before it took the lock", async () => {
    const { db, tab, at } = setup();
    const now = T0 + 3 * RECORDING_TTL_MS;
    at(now);
    const capturedAt = now - RECORDING_TTL_MS - HOUR;
    await seedJournal(db, "rec-1", 0, capturedAt, 3, capturedAt + 3_000);
    const list = db.listJournals.bind(db);
    let injected = false;
    db.listJournals = async (flowId, stepId) => {
      const snapshot = await list(flowId, stepId);
      if (!injected) {
        injected = true;
        // A writer adds a chunk and lets go of the part's lock before recovery asks for it.
        await db.appendChunk(addr("rec-1", 0), 3, {
          blob: new Blob(["fresh"], { type: WEBM }),
          recordedMs: 4_000,
          at: now
        });
      }
      return snapshot;
    };

    const result = await tab().scan("step-1");

    expect(injected).toBe(true);
    expect(result).toEqual({ saved: [], incomplete: false });
    expect(await device(db)).toEqual({ parts: {}, journals: [], chunks: {} });
  });

  // review finding base-vs-head F11 control: a fix must keep a journal whose lock its writer holds, with every chunk.
  it("base keeps: recovery leaves a journal whose writer holds its lock, with the chunk written after the listing", async () => {
    const { db, tab, at, lockManager } = setup();
    const now = T0 + 3 * RECORDING_TTL_MS;
    at(now);
    const capturedAt = now - RECORDING_TTL_MS - HOUR;
    await seedJournal(db, "rec-1", 0, capturedAt, 3, capturedAt + 3_000);
    lockManager.holdElsewhere(journalLockName(addr("rec-1", 0)));
    const list = db.listJournals.bind(db);
    let injected = false;
    db.listJournals = async (flowId, stepId) => {
      const snapshot = await list(flowId, stepId);
      if (!injected) {
        injected = true;
        await db.appendChunk(addr("rec-1", 0), 3, {
          blob: new Blob(["fresh"], { type: WEBM }),
          recordedMs: 4_000,
          at: now
        });
      }
      return snapshot;
    };

    await tab().scan("step-1");

    const prefix = KEY("rec-1", 0);
    expect(await device(db)).toEqual({
      parts: {},
      journals: [prefix],
      chunks: {
        [`${prefix}::000000`]: "c0",
        [`${prefix}::000001`]: "c1",
        [`${prefix}::000002`]: "c2",
        [`${prefix}::000003`]: "fresh"
      }
    });
    expect(db.journals.get(prefix)?.lastChunkAt).toBe(now);
  });

  // review finding F6 (plan review; base-vs-head F6): a fix must not store a chunk whose journal is gone, or must keep it findable; no scan may leave unreachable audio behind.
  it("base loses: a chunk written after its recording was deleted is kept without a journal, and no scan finds it", async () => {
    const { db, tab, at } = setup();
    const writer = tab();
    const journal = writer.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    const part = recorded(0, T0);
    journal.begin(part);
    journal.append(part, new Blob(["c0"], { type: WEBM }), 1_000);
    await flush();
    expect(Object.keys((await device(db)).chunks)).toEqual([`${KEY("rec-1", 0)}::000000`]);

    await db.deleteSession("flow-1", "step-1", "rec-1");
    journal.append(part, new Blob(["c1"], { type: WEBM }), 2_000);
    await flush();
    const orphan = { parts: {}, journals: [], chunks: { [`${KEY("rec-1", 0)}::000001`]: "c1" } };
    expect(await device(db)).toEqual(orphan);

    expect((await tab().scan("step-1")).saved).toEqual([]);
    at(T0 + 2 * RECORDING_TTL_MS);
    expect((await tab().scan("step-1")).saved).toEqual([]);
    expect(await device(db)).toEqual(orphan);
  });

  // review finding base-vs-head F6b: a fix must keep an old part and the live journal another form writes, and the writer's next chunk under that journal.
  it("base keeps: another form's scan leaves an old part and the live journal a form writes, and the next chunk lands in it", async () => {
    const { db, tab, at } = setup();
    const now = T0 + 2 * RECORDING_TTL_MS;
    at(now);
    await seedPart(db, "rec-1", 0, now - RECORDING_TTL_MS - HOUR, "part0");
    const writer = tab();
    const journal = writer.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    const part = recorded(1, now - 5_000);
    journal.begin(part);
    journal.append(part, new Blob(["c0"], { type: WEBM }), 1_000);
    await flush();

    const result = await tab().scan("step-1");
    journal.append(part, new Blob(["c1"], { type: WEBM }), 2_000);
    await flush();

    expect(result.saved).toEqual([expect.objectContaining({ sessionId: "rec-1", parts: 1 })]);
    expect(await device(db)).toEqual({
      parts: { [KEY("rec-1", 0)]: "part0" },
      journals: [KEY("rec-1", 1)],
      chunks: { [`${KEY("rec-1", 1)}::000000`]: "c0", [`${KEY("rec-1", 1)}::000001`]: "c1" }
    });
  });

  // review finding F6 trigger (plan "the lock today": a paused part holds its lock, no deletion asks for it): a fix must not delete a recording whose tab holds a part, however long it is paused.
  it("base loses: another form's scan deletes a recording whose tab holds a part paused past a day, and the next chunk is kept without a journal", async () => {
    const { db, tab, at, lockManager } = setup();
    await seedPart(db, "rec-1", 0, T0 - HOUR, "part0");
    const writer = tab();
    const journal = writer.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    const part = recorded(1, T0);
    journal.begin(part);
    journal.append(part, new Blob(["c0"], { type: WEBM }), 1_000);
    await flush();
    expect(lockManager.isHeld(journalLockName(addr("rec-1", 1)))).toBe(true);

    at(T0 + RECORDING_TTL_MS + 60_000);
    await tab().scan("step-1");

    expect(lockManager.isHeld(journalLockName(addr("rec-1", 1)))).toBe(true);
    expect(await device(db)).toEqual({ parts: {}, journals: [], chunks: {} });

    // The tab resumes: the chunk lands with no journal; Stop then stores only this part.
    journal.append(part, new Blob(["c1"], { type: WEBM }), 2_000);
    await flush();
    expect(await device(db)).toEqual({
      parts: {},
      journals: [],
      chunks: { [`${KEY("rec-1", 1)}::000001`]: "c1" }
    });
    expect(await writer.keepPart("step-1", finished(1, "c0c1", T0))).toBe("device");
    expect(await device(db)).toEqual({
      parts: { [KEY("rec-1", 1)]: "c0c1" },
      journals: [],
      chunks: {}
    });
  });

  // lock map S3 (a recording paused in its first part is not deleted): a fix must keep a held first part however long it is paused.
  it("base keeps: a recording paused past a day in its first part, held by its tab, stays and takes its next chunk", async () => {
    const { db, tab, at } = setup();
    const writer = tab();
    const journal = writer.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    const part = recorded(0, T0);
    journal.begin(part);
    journal.append(part, new Blob(["c0"], { type: WEBM }), 1_000);
    await flush();

    at(T0 + RECORDING_TTL_MS + HOUR);
    const result = await tab().scan("step-1");
    journal.append(part, new Blob(["c1"], { type: WEBM }), 2_000);
    await flush();

    expect(result).toEqual({ saved: [], incomplete: false });
    expect(await device(db)).toEqual({
      parts: {},
      journals: [KEY("rec-1", 0)],
      chunks: { [`${KEY("rec-1", 0)}::000000`]: "c0", [`${KEY("rec-1", 0)}::000001`]: "c1" }
    });
  });

  // plan table row "continued after reload, idle past 24 h" (finding F8 with Web Locks): a fix must not delete a recording a form has continued and still holds.
  it("base loses: with Web Locks, another form's scan deletes a recording a form continued and holds idle", async () => {
    const { db, tab, at } = setup();
    await seedPart(db, "rec-1", 0, T0 - 23 * HOUR, "part0");
    const holder = tab();
    const parts = await holder.readSession("step-1", "rec-1");
    holder.adopt("step-1", parts);

    at(T0 + 2 * HOUR);
    await tab().scan("step-1");

    expect(parts.map((p) => p.index)).toEqual([0]);
    expect(await device(db)).toEqual({ parts: {}, journals: [], chunks: {} });
    expect(holder.keeping("step-1", "rec-1", 0)).toBe("device");
  });

  // review finding F8 (plan review; base-vs-head F8): a fix must not delete a recording a form holds when the browser has no Web Locks.
  it("base loses: without Web Locks, another form's scan deletes a recording a form continued and holds idle", async () => {
    const { db, tab, at } = setup({ locks: false });
    await seedPart(db, "rec-1", 0, T0 - 23 * HOUR, "part0");
    const holder = tab();
    const parts = await holder.readSession("step-1", "rec-1");
    holder.adopt("step-1", parts);

    at(T0 + 2 * HOUR);
    await tab().scan("step-1");

    expect(parts.map((p) => p.index)).toEqual([0]);
    expect(await device(db)).toEqual({ parts: {}, journals: [], chunks: {} });
    expect(holder.keeping("step-1", "rec-1", 0)).toBe("device");
  });

  // review finding F8 (MP4 and Ogg take no journal lock): a fix must not delete the stored parts of a recording whose tab records an unjournaled part.
  it("base loses: while a continued recording records an MP4 part, another form's scan deletes its stored part", async () => {
    const { db, tab, at } = setup();
    await seedPart(db, "rec-1", 0, T0 - 23 * HOUR, "part0");
    const holder = tab();
    holder.adopt("step-1", await holder.readSession("step-1", "rec-1"));
    const journal = holder.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    const part = recorded(1, T0 + HOUR, MP4);
    journal.begin(part);
    journal.append(part, new Blob(["m0"], { type: MP4 }), 1_000);
    await flush();
    expect(holder.degradation("step-1")).toBe("unavailable");

    at(T0 + 2 * HOUR);
    await tab().scan("step-1");
    expect(await device(db)).toEqual({ parts: {}, journals: [], chunks: {} });

    expect(await holder.keepPart("step-1", finished(1, "m0m1", T0 + HOUR, MP4))).toBe("device");
    expect(await device(db)).toEqual({
      parts: { [KEY("rec-1", 1)]: "m0m1" },
      journals: [],
      chunks: {}
    });
  });

  // review finding F7 (plan review; base-vs-head F7): a fix must keep both forms' audio, or admit only one writer, and never leave a form's part marked as on the device when it is not.
  it("base loses: two forms that continue the same recording store the same next part, and the second replaces the first", async () => {
    const { db, tab } = setup();
    await seedPart(db, "rec-1", 0, T0 - 60_000, "part0");
    const a = tab();
    const b = tab();
    const partsA = await a.readSession("step-1", "rec-1");
    const partsB = await b.readSession("step-1", "rec-1");
    a.adopt("step-1", partsA);
    b.adopt("step-1", partsB);
    // The form's rule for the next part (run-recorder.tsx): one past the highest index of its rows.
    const next = (parts: StoredPart[]) => parts.reduce((n, p) => Math.max(n, p.index + 1), 0);
    expect([next(partsA), next(partsB)]).toEqual([1, 1]);

    expect(await a.keepPart("step-1", finished(next(partsA), "AAAA", T0))).toBe("device");
    expect(await b.keepPart("step-1", finished(next(partsB), "BBBBBB", T0 + 1))).toBe("device");

    expect(await device(db)).toEqual({
      parts: { [KEY("rec-1", 0)]: "part0", [KEY("rec-1", 1)]: "BBBBBB" },
      journals: [],
      chunks: {}
    });
    expect(a.keeping("step-1", "rec-1", 1)).toBe("device");
  });

  // plan table row "journals cannot be read": a fix must delete nothing while it cannot read a recording's journals.
  it("base keeps: an expired-looking recording stays while its journals cannot be read", async () => {
    const { db, tab, at } = setup();
    at(T0 + 2 * RECORDING_TTL_MS);
    await seedPart(db, "rec-1", 0, T0, "part0");
    db.listJournals = async () => {
      throw new Error("unreadable");
    };

    const result = await tab().scan("step-1");

    expect(result).toEqual({ saved: [], incomplete: true });
    expect(await device(db)).toEqual({
      parts: { [KEY("rec-1", 0)]: "part0" },
      journals: [],
      chunks: {}
    });
  });

  // plan choice 2 and table row "expired journal in a live recording" (review finding F11 keeps the policy): a fix must keep the live parts; dropping the expired journal is a retention decision, made only after re-reading it under its lock.
  it("base loses: recovery drops an expired journal of a recording that is still live, without rebuilding it", async () => {
    const { db, tab, at } = setup();
    const now = T0 + 2 * RECORDING_TTL_MS;
    at(now);
    await seedJournal(db, "rec-1", 0, now - 26 * HOUR, 3, now - 25 * HOUR);
    await seedPart(db, "rec-1", 1, now - HOUR, "part1");

    const result = await tab().scan("step-1");

    expect(result.saved).toEqual([expect.objectContaining({ sessionId: "rec-1", parts: 1 })]);
    expect(await device(db)).toEqual({
      parts: { [KEY("rec-1", 1)]: "part1" },
      journals: [],
      chunks: {}
    });
  });

  // review finding F9 ("hold ownership through already-accepted writes"): a fix that lets go when the form goes must still write the chunks a left part had queued.
  it("base keeps: chunks queued before the form left mid-part are written once the lock comes, and rebuilt by the next scan", async () => {
    const { db, tab, lockManager } = setup();
    const writer = tab();
    const journal = writer.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    const part = recorded(0, T0);
    const grant = lockManager.deferGrants();
    journal.begin(part);
    journal.append(part, new Blob(["c0"], { type: WEBM }), 1_000);
    journal.append(part, new Blob(["c1"], { type: WEBM }), 2_000);
    journal.leave(part);
    await flush();
    expect(await device(db)).toEqual({ parts: {}, journals: [], chunks: {} });

    grant();
    await flush();
    expect(lockManager.heldNames()).toEqual([]);

    const result = await tab().scan("step-1");

    expect(await device(db)).toEqual({
      parts: { [KEY("rec-1", 0)]: "c0c1" },
      journals: [],
      chunks: {}
    });
    expect(db.parts.get(KEY("rec-1", 0))).toMatchObject({ interrupted: true, durationMs: 2_000 });
    expect(result.saved).toEqual([expect.objectContaining({ sessionId: "rec-1", parts: 1 })]);
  });
});
