import { describe, expect, it, vi } from "vitest";
import { RecordingKeeper, resumeRefusal, type JournalPart } from "../recording-keeper";
import { memoryRecordings, type ContractSnapshot } from "../recording-store";
import { fakeLocks } from "./catalog-locks";

/**
 * What the base does in the orderings a review of an earlier build
 * reproduced: two forms (tabs) on one device store and one lock manager.
 * Each test states the base's exact keys and bytes afterwards.
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

function setup() {
  const db = memoryRecordings();
  const lockManager = fakeLocks();
  /** A form opened by the same person in another tab of this browser. */
  const tab = () => new RecordingKeeper("flow-1", "user-a", db, lockManager.locks, () => START);
  return { db, lockManager, tab };
}

const part = (index: number, sessionId = "rec-1"): JournalPart => ({
  sessionId,
  index,
  mimeType: WEBM,
  capturedAt: START + index * 60_000
});

const key = (index: number, sessionId = "rec-1") =>
  `flow-1::step-1::${sessionId}::${String(index).padStart(4, "0")}`;
const lockOf = (index: number, sessionId = "rec-1") =>
  `eneo-flow-recording:${key(index, sessionId)}`;

const finished = (index: number, bytes: string[], sessionId = "rec-1", mimeType = WEBM) => ({
  sessionId,
  index,
  blob: new Blob(bytes, { type: mimeType }),
  mimeType,
  durationMs: bytes.length * 1_000,
  capturedAt: START + index * 60_000,
  contract: CONTRACT,
  streamed: false
});

/** Lets queued writes land. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function gate() {
  let open = () => {};
  const shut = new Promise<void>((resolve) => {
    open = resolve;
  });
  return { shut, open };
}

const keys = (map: Map<string, unknown>) => [...map.keys()];

async function texts(db: ReturnType<typeof memoryRecordings>) {
  return Promise.all([...db.parts.values()].map((stored) => stored.blob.text()));
}

describe("catalog: orderings of a full write, a close and offers (base behaviour)", () => {
  // build review B F3 (first ordering): a fix must keep the part's journal lock until its full write settles, so another tab's scan never replaces the full part with the shorter journal copy.
  it("base keeps: the full part when another tab scans while its write is still being stored", async () => {
    const { db, tab } = setup();
    const a = tab();
    const b = tab();
    const journal = a.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(0));
    journal.append(part(0), new Blob(["a"], { type: WEBM }), 1_000);
    journal.append(part(0), new Blob(["b"], { type: WEBM }), 2_000);
    await settle();
    expect(keys(db.chunks)).toEqual([`${key(0)}::000000`, `${key(0)}::000001`]);

    // The finished part is handed over; its write is held. Closing the form calls
    // nothing on the keeper for a handed-over part (the recorder leaves only parts not handed over).
    const write = gate();
    const putPart = db.putPart.bind(db);
    vi.spyOn(db, "putPart").mockImplementationOnce(async (stored) => {
      await write.shut;
      return putPart(stored);
    });
    const kept = a.keepPart("step-1", finished(0, ["a", "b", "c"]));
    await settle();

    // The other tab's scan finds the journal's lock held and prepares no rebuild.
    const readChunks = vi.spyOn(db, "readChunks");
    expect(await b.scan("step-1")).toEqual({ saved: [], incomplete: false });
    expect(readChunks).not.toHaveBeenCalled();
    expect(keys(db.journals)).toEqual([key(0)]);

    write.open();
    expect(await kept).toBe("device");
    await settle();
    expect(keys(db.parts)).toEqual([key(0)]);
    expect(await texts(db)).toEqual(["abc"]);
    expect(db.parts.get(key(0))).toMatchObject({ interrupted: false, durationMs: 3_000 });
    expect(keys(db.journals)).toEqual([]);
    expect(keys(db.chunks)).toEqual([]);
    const after = await b.scan("step-1");
    expect(after.saved).toMatchObject([{ sessionId: "rec-1", parts: 1, interruptedAt: null }]);
    expect(await texts(db)).toEqual(["abc"]);
  });

  // build review B F3 (second ordering): not lost audio but a leftover; a fix must leave nothing of a discarded recording on the device, also a journal chunk whose write was pending when its tab closed.
  it("base keeps: a pending chunk of a closed tab lands after another tab discarded the recording, with no journal or part", async () => {
    const { db, tab, lockManager } = setup();
    const a = tab();
    const b = tab();
    expect(await a.keepPart("step-1", finished(0, ["p0"]))).toBe("device");
    const journal = a.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(1));
    journal.append(part(1), new Blob(["a"], { type: WEBM }), 1_000);
    await settle();

    const append = gate();
    const appendChunk = db.appendChunk.bind(db);
    vi.spyOn(db, "appendChunk").mockImplementationOnce(async (address, seq, chunk) => {
      await append.shut;
      return appendChunk(address, seq, chunk);
    });
    journal.append(part(1), new Blob(["b"], { type: WEBM }), 2_000);
    // The tab closes mid-part: the recorder leaves the part, which drains before letting go.
    journal.leave(part(1));
    await settle();
    expect(lockManager.isHeld(lockOf(1))).toBe(true);

    // The other tab is offered the recording and discards it.
    expect((await b.scan("step-1")).saved).toMatchObject([{ sessionId: "rec-1", parts: 1 }]);
    expect(await b.forgetSession("step-1", "rec-1")).toBe(true);
    expect(keys(db.parts)).toEqual([]);
    expect(keys(db.journals)).toEqual([]);
    expect(keys(db.chunks)).toEqual([]);

    append.open();
    await settle();
    await settle();
    expect(lockManager.isHeld(lockOf(1))).toBe(false);
    expect(keys(db.parts)).toEqual([]);
    expect(keys(db.journals)).toEqual([]);
    expect(keys(db.chunks)).toEqual([`${key(1)}::000001`]);
    expect(await db.chunks.get(`${key(1)}::000001`)!.blob.text()).toBe("b");
    // No later scan finds it: it has no journal and no part.
    expect(await b.scan("step-1")).toEqual({ saved: [], incomplete: false });
    expect(keys(db.chunks)).toEqual([`${key(1)}::000001`]);
  });

  // build review B F7: a fix that ties writes to a lock must keep a part whose lock request failed in the tab and uploading, never authorise or drop it because a later part's request succeeded.
  it("base keeps: a part whose journal lock request threw is stored whole on the device when the next part's request succeeds", async () => {
    const { db, tab, lockManager } = setup();
    const a = tab();
    const journal = a.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    lockManager.failRequests(lockOf(0));
    journal.begin(part(0));
    journal.append(part(0), new Blob(["a"], { type: WEBM }), 1_000);
    await settle();
    expect(a.degradation("step-1")).toBe("failed");
    expect(keys(db.journals)).toEqual([]);

    // Rotation: the next part starts before the previous one is handed over.
    lockManager.failRequests(null);
    journal.begin(part(1));
    journal.append(part(1), new Blob(["x"], { type: WEBM }), 1_000);
    await settle();
    expect(keys(db.journals)).toEqual([key(1)]);

    expect(await a.keepPart("step-1", finished(0, ["whole", "0"]))).toBe("device");
    expect(a.keeping("step-1", "rec-1", 0)).toBe("device");
    expect(keys(db.parts)).toEqual([key(0)]);
    expect(await texts(db)).toEqual(["whole0"]);
    expect(keys(db.journals)).toEqual([key(1)]);
    expect(keys(db.chunks)).toEqual([`${key(1)}::000000`]);
    expect(lockManager.isHeld(lockOf(1))).toBe(true);
  });

  // build review B F10: a fix that stops a closed form's writes must leave the left part either rebuilt with its exact bytes or its journal intact, never dropped without the part stored.
  it("base keeps: a scan whose form closed while it read the journals still rebuilds the left part and drops its journal", async () => {
    const { db, tab } = setup();
    const a = tab();
    expect(await a.keepPart("step-1", finished(0, ["p0"]))).toBe("device");
    const journal = a.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(1));
    journal.append(part(1), new Blob(["a"], { type: WEBM }), 1_000);
    journal.append(part(1), new Blob(["b"], { type: WEBM }), 2_000);
    journal.leave(part(1));
    await settle();

    const b = tab();
    const read = gate();
    const listJournals = db.listJournals.bind(db);
    vi.spyOn(db, "listJournals").mockImplementationOnce(async (flowId, stepId) => {
      await read.shut;
      return listJournals(flowId, stepId);
    });
    const scanning = b.scan("step-1");
    await settle();
    // The form closes here: the base keeper has no close, so nothing stops the scan.
    expect(keys(db.journals)).toEqual([key(1)]);

    read.open();
    const result = await scanning;
    expect(result.saved).toMatchObject([{ sessionId: "rec-1", parts: 2 }]);
    expect(keys(db.parts)).toEqual([key(0), key(1)]);
    expect(await texts(db)).toEqual(["p0", "ab"]);
    expect(db.parts.get(key(1))).toMatchObject({ interrupted: true, durationMs: 2_000 });
    expect(keys(db.journals)).toEqual([]);
    expect(keys(db.chunks)).toEqual([]);
  });

  // build review B F11: a fix must include in Continue every part another tab rebuilt between the offer and the read, and number the next part above them.
  it("base keeps: Continue reads the part another tab rebuilt after the offer was read", async () => {
    const { db, tab, lockManager } = setup();
    const a = tab();
    expect(await a.keepPart("step-1", finished(0, ["p0"]))).toBe("device");
    expect(await a.keepPart("step-1", finished(1, ["p1"]))).toBe("device");
    const journal = a.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(2));
    journal.append(part(2), new Blob(["a"], { type: WEBM }), 1_000);
    journal.append(part(2), new Blob(["b"], { type: WEBM }), 2_000);
    journal.leave(part(2));
    await settle();
    // A closed tab still holds the part's lock when the form reads its offer.
    lockManager.holdElsewhere(lockOf(2));
    const b = tab();
    expect((await b.scan("step-1")).saved).toMatchObject([{ sessionId: "rec-1", parts: 2 }]);
    expect(keys(db.journals)).toEqual([key(2)]);

    // The browser lets go; a third tab's scan rebuilds the part.
    lockManager.releaseElsewhere(lockOf(2));
    await tab().scan("step-1");
    expect(keys(db.journals)).toEqual([]);

    // Continue on the base: read the parts, check the step, adopt.
    const parts = await b.readSession("step-1", "rec-1");
    expect(parts.map((stored) => stored.index)).toEqual([0, 1, 2]);
    expect(await Promise.all(parts.map((stored) => stored.blob.text()))).toEqual([
      "p0",
      "p1",
      "ab"
    ]);
    expect(parts[2]).toMatchObject({ interrupted: true });
    expect(resumeRefusal(CONTRACT, parts)).toBeNull();
    b.adopt("step-1", parts);
    expect(b.keeping("step-1", "rec-1", 2)).toBe("device");
    // The form numbers the next part one above its highest row.
    expect(Math.max(...parts.map((stored) => stored.index)) + 1).toBe(3);
    expect(keys(db.parts)).toEqual([key(0), key(1), key(2)]);
  });

  // build review B F5 (device side only; which offer the form shows is not run here): a fix must leave a refused recording and the one passed over with "Not now" untouched on the device and offered again.
  it("base keeps: a refused Continue and Not now leave both recordings on the device, offered again on the next open", async () => {
    const { db, tab } = setup();
    const a = tab();
    // The newer recording is offered first; the step no longer accepts its type.
    expect(await a.keepPart("step-1", finished(0, ["b0"], "rec-b"))).toBe("device");
    expect(
      await a.keepPart("step-1", {
        ...finished(0, ["a0"], "rec-a", "audio/ogg"),
        capturedAt: START + 3_600_000
      })
    ).toBe("device");

    const form = tab();
    const offers = (await form.scan("step-1")).saved;
    expect(offers.map((saved) => saved.sessionId)).toEqual(["rec-a", "rec-b"]);
    const parts = await form.readSession("step-1", "rec-a");
    expect(resumeRefusal(CONTRACT, parts)).toBe("type_not_accepted");
    // Refused: nothing adopted; "Not now" calls nothing on the keeper.

    expect(keys(db.parts)).toEqual([key(0, "rec-b"), key(0, "rec-a")]);
    expect(await texts(db)).toEqual(["b0", "a0"]);
    expect(keys(db.journals)).toEqual([]);
    expect(keys(db.chunks)).toEqual([]);
    const again = (await tab().scan("step-1")).saved;
    expect(again.map((saved) => saved.sessionId)).toEqual(["rec-a", "rec-b"]);
  });
});
