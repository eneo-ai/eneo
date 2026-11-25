import { describe, expect, it, vi } from "vitest";
import { JOURNAL_MAX_PENDING_CHUNKS } from "../recording-journal";
import { RecordingKeeper, storedPartFile, type JournalPart } from "../recording-keeper";
import {
  memoryRecordings,
  RECORDING_TTL_MS,
  type ContractSnapshot,
  type JournalMeta
} from "../recording-store";
import { fakeLocks } from "./catalog-locks";

/**
 * What the keeper, the journal and the store do today, byte for byte, in the
 * orderings reviews have reproduced. "base loses" marks audio lost today, to be
 * fixed; "base keeps" marks audio kept today, which no fix may make worse.
 * Tabs share one store and one lock manager; a tab that closes or crashes is a
 * keeper with a lock manager of its own, as the browser lets go of its locks.
 */

const CONTRACT: ContractSnapshot = {
  publishedFlowVersion: 4,
  inputFormat: "audio",
  maxFiles: 4,
  maxFileSizeBytes: 10_000_000,
  acceptedMimetypes: ["audio/webm"]
};
const START = Date.UTC(2026, 9, 22, 8, 0, 0);
const WEBM = "audio/webm;codecs=opus";
const MP4 = "audio/mp4";
const STEP = "step-1";
const REC = "rec-1";

type Db = ReturnType<typeof memoryRecordings>;
type Locks = ReturnType<typeof fakeLocks>;

const K = (index: number) => `flow-1::${STEP}::${REC}::${String(index).padStart(4, "0")}`;
const C = (index: number, seq: number) => `${K(index)}::${String(seq).padStart(6, "0")}`;
const LOCK = (index: number) => `eneo-flow-recording:${K(index)}`;

function device({ locks = true } = {}) {
  const db = memoryRecordings();
  const shared = fakeLocks();
  let now = START;
  /** A form in a tab of this browser; another lock manager stands for a tab that went away. */
  const tab = (lockManager: Locks | null = locks ? shared : null) =>
    new RecordingKeeper("flow-1", "user-a", db, lockManager?.locks ?? null, () => now);
  return {
    db,
    locks: shared,
    tab,
    later: (ms: number) => {
      now += ms;
    }
  };
}

const jpart = (index: number, mimeType = WEBM): JournalPart => ({
  sessionId: REC,
  index,
  mimeType,
  capturedAt: START + index * 60_000
});

const finished = (index: number, audio: string, mimeType = "audio/webm") => ({
  sessionId: REC,
  index,
  blob: new Blob([audio], { type: mimeType }),
  mimeType,
  durationMs: 1_000,
  capturedAt: START + index * 60_000,
  contract: CONTRACT,
  streamed: false
});

const audio = (text: string) => new Blob([text], { type: "audio/webm" });
const journalOf = (keeper: RecordingKeeper) =>
  keeper.journalFor(
    STEP,
    () => CONTRACT,
    () => false
  );

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const flush = async () => {
  for (let round = 0; round < 5; round += 1) await settle();
};

function gate() {
  let open = () => {};
  const opened = new Promise<void>((resolve) => {
    open = resolve;
  });
  return { opened, open };
}

/** Every part, journal and chunk on the device, by key, with its audio as text. */
async function onDevice(db: Db) {
  const text = async (map: Map<string, { blob: Blob }>) =>
    Object.fromEntries(
      await Promise.all([...map].map(async ([key, row]) => [key, await row.blob.text()] as const))
    );
  return {
    parts: await text(db.parts),
    journals: [...db.journals.keys()],
    chunks: await text(db.chunks)
  };
}

const EMPTY = { parts: {}, journals: [], chunks: {} };

/** The device's parts in order: number, rebuilt or not, audio. */
async function partsInOrder(db: Db) {
  const parts = [...db.parts.values()].sort((a, b) => a.index - b.index);
  return Promise.all(
    parts.map(async (kept) => [kept.index, kept.interrupted, await kept.blob.text()])
  );
}

/** "Fortsätt inspelningen" as the base form does it: read, adopt, next number from the rows. */
async function continueAsBase(keeper: RecordingKeeper): Promise<number> {
  const parts = await keeper.readSession(STEP, REC);
  keeper.adopt(STEP, parts);
  return Math.max(-1, ...parts.map((kept) => kept.index)) + 1;
}

describe("catalog: memory release and tab map", () => {
  describe("a removed last part and its replacement at the same number", () => {
    // memory-change review F1: a removed part's late store must not mark its replacement as on the device.
    it("base keeps: a replacement whose write failed is rebuilt from its journal once the tab goes, though the keeper says it is on the device", async () => {
      const { db, tab } = device();
      const keeper = tab();
      const journal = journalOf(keeper);
      await keeper.keepPart(STEP, finished(0, "part0"));
      const stall = gate();
      const appendChunk = db.appendChunk.bind(db);
      let stallNext = true;
      vi.spyOn(db, "appendChunk").mockImplementation(async (...args) => {
        if (stallNext) {
          stallNext = false;
          await stall.opened;
        }
        return appendChunk(...args);
      });
      journal.begin(jpart(1));
      journal.append(jpart(1), audio("OLD-c"), 500);
      await flush();
      // Stored; its journal's last chunk is still being written, so its commit waits.
      const old = keeper.keepPart(STEP, finished(1, "OLD"));
      await flush();
      expect(keeper.keeping(STEP, REC, 1)).toBeUndefined();
      await keeper.forgetPart(STEP, REC, 1);

      journal.begin(jpart(1));
      journal.append(jpart(1), audio("N1"), 1_000);
      journal.append(jpart(1), audio("N2"), 2_000);
      vi.spyOn(db, "putPart").mockRejectedValueOnce(new Error("QuotaExceededError"));
      expect(await keeper.keepPart(STEP, finished(1, "N1N2"))).toBe("tab");
      expect(keeper.keeping(STEP, REC, 1)).toBe("tab");

      stall.open();
      expect(await old).toBe("device");
      await flush();
      expect(keeper.keeping(STEP, REC, 1)).toBe("device");
      expect(await onDevice(db)).toEqual({
        parts: { [K(0)]: "part0" },
        journals: [K(1)],
        chunks: { [C(1, 0)]: "N1", [C(1, 1)]: "N2" }
      });

      await tab(fakeLocks()).scan(STEP);
      expect(await partsInOrder(db)).toEqual([
        [0, false, "part0"],
        [1, true, "N1N2"]
      ]);
    });

    // memory-change review F1 with the pending-chunk cap: a replacement must keep its whole audio on the device, or say it is only in this tab.
    it("base loses: a replacement recorded while the removed part's last chunk is still written keeps only its first 30 chunks on the device", async () => {
      const { db, tab } = device();
      const keeper = tab();
      const journal = journalOf(keeper);
      await keeper.keepPart(STEP, finished(0, "part0"));
      const stall = gate();
      const appendChunk = db.appendChunk.bind(db);
      let stallNext = true;
      vi.spyOn(db, "appendChunk").mockImplementation(async (...args) => {
        if (stallNext) {
          stallNext = false;
          await stall.opened;
        }
        return appendChunk(...args);
      });
      journal.begin(jpart(1));
      journal.append(jpart(1), audio("OLD-c"), 500);
      await flush();
      const old = keeper.keepPart(STEP, finished(1, "OLD"));
      await flush();
      await keeper.forgetPart(STEP, REC, 1);

      const chunks = Array.from({ length: JOURNAL_MAX_PENDING_CHUNKS + 5 }, (_, n) => `c${n}`);
      journal.begin(jpart(1));
      chunks.forEach((chunk, n) => journal.append(jpart(1), audio(chunk), (n + 1) * 1_000));
      vi.spyOn(db, "putPart").mockRejectedValueOnce(new Error("QuotaExceededError"));
      expect(await keeper.keepPart(STEP, finished(1, chunks.join("")))).toBe("tab");
      stall.open();
      await old;
      await flush();
      expect(keeper.keeping(STEP, REC, 1)).toBe("device");
      expect(keeper.degradation(STEP)).toBe("failed");

      await tab(fakeLocks()).scan(STEP);
      expect(await partsInOrder(db)).toEqual([
        [0, false, "part0"],
        [1, true, chunks.slice(0, JOURNAL_MAX_PENDING_CHUNKS).join("")]
      ]);
    });

    // memory-change review F1 for audio that is not journaled (MP4, Ogg): the removed part must stay removed and its replacement must not be reported as on the device.
    it("base loses: an MP4 replacement whose write fails is only in the tab, while the removed part comes back on the device and counts as kept", async () => {
      const { db, tab } = device();
      const keeper = tab();
      await keeper.keepPart(STEP, finished(0, "part0", MP4));
      const write = gate();
      const putPart = db.putPart.bind(db);
      const spy = vi.spyOn(db, "putPart").mockImplementationOnce(async (part) => {
        await write.opened;
        return putPart(part);
      });
      const old = keeper.keepPart(STEP, finished(1, "OLD", MP4));
      await flush();
      await keeper.forgetPart(STEP, REC, 1);
      spy.mockRejectedValueOnce(new Error("QuotaExceededError"));
      expect(await keeper.keepPart(STEP, finished(1, "NEW", MP4))).toBe("tab");

      write.open();
      expect(await old).toBe("device");
      expect(keeper.keeping(STEP, REC, 1)).toBe("device");
      expect(await onDevice(db)).toEqual({
        parts: { [K(0)]: "part0", [K(1)]: "OLD" },
        journals: [],
        chunks: {}
      });
    });

    // source map T2: a part recorded after the last row was removed mid-store must be journaled (or say it is not), and the removed part must not come back.
    it("base loses: the removed part's late commit ends the new part's journal, so a crash leaves the removed audio in its place", async () => {
      const { db, locks, tab } = device();
      const keeper = tab();
      const journal = journalOf(keeper);
      await keeper.keepPart(STEP, finished(0, "part0"));
      journal.begin(jpart(1));
      journal.append(jpart(1), audio("O1"), 1_000);
      await flush();
      const write = gate();
      const putPart = db.putPart.bind(db);
      vi.spyOn(db, "putPart").mockImplementationOnce(async (part) => {
        await write.opened;
        return putPart(part);
      });
      const old = keeper.keepPart(STEP, finished(1, "OLD"));
      await flush();
      await keeper.forgetPart(STEP, REC, 1);

      journal.begin(jpart(1));
      journal.append(jpart(1), audio("N1"), 1_000);
      write.open();
      expect(await old).toBe("device");
      journal.append(jpart(1), audio("N2"), 2_000);
      await flush();
      expect(keeper.keeping(STEP, REC, 1)).toBe("device");
      expect(keeper.degradation(STEP)).toBeNull();
      expect(locks.isHeld(LOCK(1))).toBe(true);
      expect(await onDevice(db)).toEqual({
        parts: { [K(0)]: "part0", [K(1)]: "OLD" },
        journals: [K(1)],
        chunks: { [C(1, 0)]: "O1" }
      });

      // The tab crashes before the new part ends.
      await tab(fakeLocks()).scan(STEP);
      expect(await onDevice(db)).toEqual({
        parts: { [K(0)]: "part0", [K(1)]: "OLD" },
        journals: [],
        chunks: {}
      });
    });
  });

  describe("two forms continue the same kept recording", () => {
    // memory-change review F2, source map F7: a part one form says is on the device must never be replaced by another form's audio.
    it("base loses: both forms number the next part 1, the second replaces the first's audio, and the first still says it is kept", async () => {
      const { db, tab } = device();
      await tab().keepPart(STEP, finished(0, "part0"));
      const a = tab();
      const b = tab();
      expect(await continueAsBase(a)).toBe(1);
      expect(await continueAsBase(b)).toBe(1);
      const ja = journalOf(a);
      const jb = journalOf(b);
      ja.begin(jpart(1));
      jb.begin(jpart(1));
      ja.append(jpart(1), audio("AAAA"), 1_000);
      jb.append(jpart(1), audio("BBBB"), 1_000);
      await flush();
      expect(await a.keepPart(STEP, finished(1, "AAAA"))).toBe("device");
      await flush();
      expect(await b.keepPart(STEP, finished(1, "BBBB"))).toBe("device");
      await flush();

      expect(a.keeping(STEP, REC, 1)).toBe("device");
      const read = await a.readSession(STEP, REC);
      expect(await Promise.all(read.map((part) => part.blob.text()))).toEqual(["part0", "BBBB"]);
      expect(await onDevice(db)).toEqual({
        parts: { [K(0)]: "part0", [K(1)]: "BBBB" },
        journals: [],
        chunks: {}
      });
    });

    // source map S5: without Web Locks two forms must not replace each other's parts either.
    it("base loses: without Web Locks the second form's part replaces the first's at the same number", async () => {
      const { db, tab } = device({ locks: false });
      await tab().keepPart(STEP, finished(0, "part0"));
      const a = tab();
      const b = tab();
      expect(await continueAsBase(a)).toBe(1);
      expect(await continueAsBase(b)).toBe(1);
      expect(await a.keepPart(STEP, finished(1, "AAAA"))).toBe("device");
      expect(await b.keepPart(STEP, finished(1, "BBBB"))).toBe("device");
      expect(a.keeping(STEP, REC, 1)).toBe("device");
      expect(await onDevice(db)).toEqual({
        parts: { [K(0)]: "part0", [K(1)]: "BBBB" },
        journals: [],
        chunks: {}
      });
    });

    // source map T3 and S1b: a form that ends its own recording must not remove parts another form recorded.
    it("base loses: a form that continued the recording and starts its run removes the other form's part", async () => {
      const { db, tab } = device();
      await tab().keepPart(STEP, finished(0, "part0"));
      const a = tab();
      const b = tab();
      await continueAsBase(a);
      await continueAsBase(b);
      expect(await a.keepPart(STEP, finished(1, "AAAA"))).toBe("device");
      await b.forgetAll();
      expect(a.keeping(STEP, REC, 1)).toBe("device");
      expect(await a.readSession(STEP, REC)).toEqual([]);
      expect(await onDevice(db)).toEqual(EMPTY);
    });

    // source map S4: a form that let go after "Spara och fortsätt senare" and one form that continues keep every part.
    it("base keeps: after the recording form let go, another form continues and every part stays", async () => {
      const { db, locks, tab } = device();
      const first = tab();
      const jf = journalOf(first);
      jf.begin(jpart(0));
      jf.append(jpart(0), audio("part0"), 1_000);
      await flush();
      expect(await first.keepPart(STEP, finished(0, "part0"))).toBe("device");
      await flush();
      expect(locks.heldNames()).toEqual([]);

      const other = tab();
      expect((await other.scan(STEP)).saved).toMatchObject([{ sessionId: REC, parts: 1 }]);
      const index = await continueAsBase(other);
      const jo = journalOf(other);
      jo.begin(jpart(index));
      jo.append(jpart(index), audio("BBBB"), 1_000);
      await flush();
      expect(await other.keepPart(STEP, finished(index, "BBBB"))).toBe("device");
      await flush();
      expect(await partsInOrder(db)).toEqual([
        [0, false, "part0"],
        [1, false, "BBBB"]
      ]);
      expect(db.journals.size).toBe(0);
      expect(db.chunks.size).toBe(0);
    });
  });

  describe("removal by another tab", () => {
    // memory-change review F3, source map S8: a form must not go on saying a part is on the device after another tab's day-old removal took it.
    it("base loses: another tab's removal after a day takes an open, still form's parts, and that form still says they are kept", async () => {
      const { db, tab, later } = device();
      const a = tab();
      expect(await a.keepPart(STEP, finished(0, "part0"))).toBe("device");
      later(RECORDING_TTL_MS + 60_000);
      expect((await tab().scan(STEP)).saved).toEqual([]);
      expect(a.keeping(STEP, REC, 0)).toBe("device");
      expect(await a.readSession(STEP, REC)).toEqual([]);
      expect(await onDevice(db)).toEqual(EMPTY);
    });

    // source map S3 and T3: another tab's day-old removal must not take a recording whose part a form holds, paused.
    it("base loses: a pause of over a day lets another tab remove the recording, the held journal with it", async () => {
      const { db, locks, tab, later } = device();
      const a = tab();
      const ja = journalOf(a);
      await a.keepPart(STEP, finished(0, "part0"));
      ja.begin(jpart(1));
      ja.append(jpart(1), audio("P1"), 1_000);
      await flush();
      later(RECORDING_TTL_MS + 120_000);
      expect((await tab().scan(STEP)).saved).toEqual([]);
      expect(locks.isHeld(LOCK(1))).toBe(true);
      expect(await onDevice(db)).toEqual(EMPTY);
      expect(a.keeping(STEP, REC, 0)).toBe("device");

      // The person goes on and stops: only part 1 is on the device.
      ja.append(jpart(1), audio("P2"), 2_000);
      expect(await a.keepPart(STEP, finished(1, "P1P2"))).toBe("device");
      await flush();
      expect(await onDevice(db)).toEqual({ parts: { [K(1)]: "P1P2" }, journals: [], chunks: {} });
    });

    // source map T3: "Kassera inspelningen" in another tab must not remove a recording a form is recording.
    it("base loses: discarding in another tab removes the parts and the journal of the part a form is recording", async () => {
      const { db, tab } = device();
      const a = tab();
      const ja = journalOf(a);
      await a.keepPart(STEP, finished(0, "part0"));
      ja.begin(jpart(1));
      ja.append(jpart(1), audio("A1"), 1_000);
      await flush();
      const b = tab();
      expect((await b.scan(STEP)).saved).toMatchObject([{ sessionId: REC, parts: 1 }]);
      expect(await b.forgetSession(STEP, REC)).toBe(true);
      expect(await onDevice(db)).toEqual(EMPTY);
      expect(a.keeping(STEP, REC, 0)).toBe("device");

      ja.append(jpart(1), audio("A2"), 2_000);
      expect(await a.keepPart(STEP, finished(1, "A1A2"))).toBe("device");
      await flush();
      expect(await onDevice(db)).toEqual({ parts: { [K(1)]: "A1A2" }, journals: [], chunks: {} });
    });
  });

  describe("a tab closes mid-part and another continues the recording", () => {
    /**
     * Tab A keeps parts 0 and 1 and journals part 2, then closes: nothing
     * commits or leaves. A's own lock manager stands for its tab; in the
     * shared one its part's lock is held elsewhere until the tab closes.
     */
    async function tabClosesMidPart(chunks: string[]) {
      const context = device();
      const tabA = context.tab(fakeLocks());
      for (const index of [0, 1]) await tabA.keepPart(STEP, finished(index, `part${index}`));
      const journalA = journalOf(tabA);
      journalA.begin(jpart(2));
      chunks.forEach((chunk, n) => journalA.append(jpart(2), audio(chunk), (n + 1) * 1_000));
      await flush();
      context.locks.holdElsewhere(LOCK(2));
      return { ...context, closeA: () => context.locks.releaseElsewhere(LOCK(2)) };
    }

    async function recordNext(keeper: RecordingKeeper, index: number, text: string) {
      const journal = journalOf(keeper);
      journal.begin(jpart(index));
      journal.append(jpart(index), audio(text), 1_000);
      await flush();
    }

    // source map T1, cut tested 18:13 (red): a continuation from an offer read while the part was held must keep the closed tab's audio.
    it("base loses: the other tab continues from an earlier scan, takes number 2 and its part replaces the closed tab's audio", async () => {
      const { db, tab, closeA } = await tabClosesMidPart(["AAAA"]);
      const tabB = tab();
      // Its form was open already: the scan ran while A held the part, and counted only stored parts.
      expect((await tabB.scan(STEP)).saved).toMatchObject([{ sessionId: REC, parts: 2 }]);
      closeA();
      const index = await continueAsBase(tabB);
      expect(index).toBe(2);
      await recordNext(tabB, index, "BBBB");
      expect(await tabB.keepPart(STEP, finished(index, "BBBB"))).toBe("device");
      await flush();
      expect(await partsInOrder(db)).toEqual([
        [0, false, "part0"],
        [1, false, "part1"],
        [2, false, "BBBB"]
      ]);
      expect(db.journals.size).toBe(0);
      expect(db.chunks.size).toBe(0);
    });

    // source map T1, crash variant: the closed tab's chunks must not be mixed with the continuing tab's.
    it("base loses: the continuing tab crashes mid-part, and the rebuilt part mixes its first chunk with the closed tab's second", async () => {
      const { db, tab, closeA } = await tabClosesMidPart(["A0", "A1"]);
      const tabB = tab();
      expect((await tabB.scan(STEP)).saved).toMatchObject([{ sessionId: REC, parts: 2 }]);
      closeA();
      const index = await continueAsBase(tabB);
      await recordNext(tabB, index, "B0");
      expect(await onDevice(db)).toMatchObject({
        journals: [K(2)],
        chunks: { [C(2, 0)]: "B0", [C(2, 1)]: "A1" }
      });

      await tab(fakeLocks()).scan(STEP);
      expect(await partsInOrder(db)).toEqual([
        [0, false, "part0"],
        [1, false, "part1"],
        [2, true, "B0A1"]
      ]);
    });

    // source map T1, cut tested 18:13 (green): a scan after the tab closed rebuilds its part, and continuing then keeps it.
    it("base keeps: the other tab scans again before it continues, rebuilds the closed tab's part and numbers its own 3", async () => {
      const { db, tab, closeA } = await tabClosesMidPart(["AAAA"]);
      const tabB = tab();
      closeA();
      expect((await tabB.scan(STEP)).saved).toMatchObject([{ sessionId: REC, parts: 3 }]);
      const index = await continueAsBase(tabB);
      expect(index).toBe(3);
      await recordNext(tabB, index, "BBBB");
      expect(await tabB.keepPart(STEP, finished(index, "BBBB"))).toBe("device");
      await flush();
      expect(await partsInOrder(db)).toEqual([
        [0, false, "part0"],
        [1, false, "part1"],
        [2, true, "AAAA"],
        [3, false, "BBBB"]
      ]);
      expect(db.journals.size).toBe(0);
      expect(db.chunks.size).toBe(0);
    });
  });

  // review gate 1 F3 (build gate): a form that goes while a finished part is written must not let another tab's scan replace the full part with its journal.
  it("base keeps: a finished part's full audio when another tab scans while it is still being written", async () => {
    const { db, tab } = device();
    const tabA = tab();
    const journal = journalOf(tabA);
    journal.begin(jpart(0));
    journal.append(jpart(0), audio("AA"), 500);
    await settle();
    // The full write waits until the other tab has scanned; a rebuild that scan may begin waits for the full write.
    const written = gate();
    const rebuilt = gate();
    const putPart = db.putPart.bind(db);
    vi.spyOn(db, "putPart").mockImplementation(async (stored) => {
      await (stored.interrupted ? rebuilt.opened : written.opened);
      return putPart(stored);
    });
    const kept = tabA.keepPart(STEP, finished(0, "AAAA-full"));
    await settle();
    // The form goes now: on the base that does nothing to the keeper or the part's lock.
    const scanned = tab().scan(STEP);
    await settle();
    written.open();
    expect(await kept).toBe("device");
    rebuilt.open();
    await scanned;
    await tab().scan(STEP);
    const stored = await tab().readSession(STEP, REC);
    expect(await Promise.all(stored.map((part) => part.blob.text()))).toEqual(["AAAA-full"]);
    expect(db.journals.size).toBe(0);
  });

  // source map T4: a part only this tab holds keeps its journal and lock until the tab goes, then it is rebuilt.
  it("base keeps: a part the device refused keeps its journal, another tab leaves it alone, and it is rebuilt once the tab goes", async () => {
    const { db, locks, tab } = device();
    const a = tab();
    const ja = journalOf(a);
    await a.keepPart(STEP, finished(0, "part0"));
    ja.begin(jpart(1));
    ja.append(jpart(1), audio("T1"), 1_000);
    ja.append(jpart(1), audio("T2"), 2_000);
    await flush();
    vi.spyOn(db, "putPart").mockRejectedValueOnce(new Error("QuotaExceededError"));
    expect(await a.keepPart(STEP, finished(1, "T1T2"))).toBe("tab");
    await flush();
    expect(locks.isHeld(LOCK(1))).toBe(true);
    expect((await tab().scan(STEP)).saved).toMatchObject([{ sessionId: REC, parts: 1 }]);
    expect(await onDevice(db)).toEqual({
      parts: { [K(0)]: "part0" },
      journals: [K(1)],
      chunks: { [C(1, 0)]: "T1", [C(1, 1)]: "T2" }
    });

    expect((await tab(fakeLocks()).scan(STEP)).saved).toMatchObject([{ sessionId: REC, parts: 2 }]);
    expect(await partsInOrder(db)).toEqual([
      [0, false, "part0"],
      [1, true, "T1T2"]
    ]);
    expect(db.journals.size).toBe(0);
  });

  // memory-change review F4: a kept part whose bytes cannot be read must not be offered or handed out as whole.
  it("base loses: a kept part whose bytes are gone is offered and handed out as a file, though the store's own check says it is gone", async () => {
    const { db, tab } = device();
    class BytesGone extends Blob {
      override slice(): Blob {
        return {
          arrayBuffer: () => Promise.reject(new DOMException("gone", "NotReadableError"))
        } as unknown as Blob;
      }
    }
    await db.putPart({
      flowId: "flow-1",
      stepId: STEP,
      ...finished(0, "x"),
      blob: new BytesGone(["part0"], { type: "audio/webm" }),
      interrupted: false,
      userId: "user-a"
    });
    const keeper = tab();
    expect((await keeper.scan(STEP)).saved).toMatchObject([{ sessionId: REC, parts: 1 }]);
    const [kept] = await keeper.readSession(STEP, REC);
    const file = storedPartFile(kept!);
    expect([file.name, file.size]).toEqual([
      "recording-rec-1-seg00-2026-10-22T08-00-00-000Z.webm",
      5
    ]);
    expect(await db.hasPart({ flowId: "flow-1", stepId: STEP, sessionId: REC, index: 0 })).toBe(
      false
    );
  });

  describe("what a scan leaves of a journal whose lock is free", () => {
    const JOURNAL: JournalMeta = {
      flowId: "flow-1",
      stepId: STEP,
      sessionId: REC,
      index: 2,
      mimeType: WEBM,
      capturedAt: START + 120_000,
      contract: CONTRACT,
      streamed: false,
      lastChunkAt: START + 120_000,
      userId: "user-a"
    };

    /** Parts 0 and 1 kept, and a journal for part 2 with these chunks by their sequence. */
    async function keptWithJournal(
      chunks: Record<number, string>,
      { locks = true, lastChunkAt = JOURNAL.lastChunkAt } = {}
    ) {
      const { db, tab } = device({ locks });
      const keeper = tab();
      for (const index of [0, 1]) await keeper.keepPart(STEP, finished(index, `part${index}`));
      await db.putJournal({ ...JOURNAL, lastChunkAt });
      for (const [seq, text] of Object.entries(chunks)) {
        await db.appendChunk(JOURNAL, Number(seq), {
          blob: audio(text),
          recordedMs: (Number(seq) + 1) * 1_000,
          at: lastChunkAt
        });
      }
      return { db, keeper };
    }

    const part2 = (db: Db) => db.parts.get(K(2));

    // scan-journal table (18:20), readable chunks: they become part 2 and the journal goes.
    it("base keeps: readable chunks are rebuilt into part 2 and the journal is dropped", async () => {
      const { db, keeper } = await keptWithJournal({ 0: "ab", 1: "cd" });
      expect(await keeper.scan(STEP)).toMatchObject({
        incomplete: false,
        saved: [{ sessionId: REC, parts: 3 }]
      });
      expect(db.journals.size).toBe(0);
      expect(db.chunks.size).toBe(0);
      expect(part2(db)).toMatchObject({ index: 2, interrupted: true });
      expect(await part2(db)!.blob.text()).toBe("abcd");
    });

    // scan-journal table (18:20), no chunks: nothing recorded, nothing made.
    it("base keeps: a journal with no chunks is dropped and makes no part", async () => {
      const { db, keeper } = await keptWithJournal({});
      expect(await keeper.scan(STEP)).toMatchObject({
        incomplete: false,
        saved: [{ sessionId: REC, parts: 2 }]
      });
      expect(db.journals.size).toBe(0);
      expect(part2(db)).toBeUndefined();
    });

    // scan-journal table (18:20), a gap: chunks after a gap must not be dropped silently.
    it("base loses: only the chunks before a gap are rebuilt, and the chunks after it are dropped with the journal", async () => {
      const { db, keeper } = await keptWithJournal({ 0: "ab", 2: "ef" });
      expect(await keeper.scan(STEP)).toMatchObject({
        incomplete: false,
        saved: [{ sessionId: REC, parts: 3 }]
      });
      expect(db.journals.size).toBe(0);
      expect(db.chunks.size).toBe(0);
      expect(await part2(db)!.blob.text()).toBe("ab");
    });

    // scan-journal table (18:20), reading throws: the journal and its chunks stay for another try.
    it("base keeps: the journal and its chunks stay when reading them throws, scan after scan", async () => {
      const { db, keeper } = await keptWithJournal({ 0: "ab" });
      vi.spyOn(db, "readChunks").mockRejectedValue(new Error("blocked"));
      for (let scan = 0; scan < 2; scan += 1) {
        expect(await keeper.scan(STEP)).toMatchObject({
          incomplete: true,
          saved: [{ sessionId: REC, parts: 2 }]
        });
        expect(db.journals.size).toBe(1);
        expect(db.chunks.size).toBe(1);
        expect(part2(db)).toBeUndefined();
      }
    });

    // scan-journal table (18:20), no answer in time: slow is not gone.
    it("base keeps: the journal and its chunks stay when they are not read in time, scan after scan", async () => {
      const { db, keeper } = await keptWithJournal({ 0: "ab" });
      vi.spyOn(db, "readChunks").mockResolvedValue(null);
      for (let scan = 0; scan < 2; scan += 1) {
        expect(await keeper.scan(STEP)).toMatchObject({
          incomplete: true,
          saved: [{ sessionId: REC, parts: 2 }]
        });
        expect(db.journals.size).toBe(1);
        expect(db.chunks.size).toBe(1);
        expect(part2(db)).toBeUndefined();
      }
    });

    // scan-journal table (18:20), expired: the day's expiry drops it; a fix must not keep expired audio.
    it("base keeps: the day's expiry, an expired journal and its chunks are dropped without a part", async () => {
      const { db, keeper } = await keptWithJournal(
        { 0: "ab" },
        { lastChunkAt: START - RECORDING_TTL_MS - 1_000 }
      );
      expect(await keeper.scan(STEP)).toMatchObject({
        incomplete: false,
        saved: [{ sessionId: REC, parts: 2 }]
      });
      expect(db.journals.size).toBe(0);
      expect(db.chunks.size).toBe(0);
      expect(part2(db)).toBeUndefined();
    });

    // scan-journal table (18:20), no Web Locks: a journal from another context stays untouched.
    it("base keeps: without Web Locks the journal and its chunks stay, scan after scan", async () => {
      const { db, keeper } = await keptWithJournal({ 0: "ab" }, { locks: false });
      for (let scan = 0; scan < 2; scan += 1) {
        expect(await keeper.scan(STEP)).toEqual({
          incomplete: false,
          saved: [expect.objectContaining({ sessionId: REC, parts: 2 })]
        });
        expect(db.journals.size).toBe(1);
        expect(db.chunks.size).toBe(1);
        expect(part2(db)).toBeUndefined();
      }
    });
  });
});
