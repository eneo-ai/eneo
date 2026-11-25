import { describe, expect, it, vi } from "vitest";
import { journalLockName } from "../recording-journal";
import { RecordingKeeper, resumeRefusal, type JournalPart } from "../recording-keeper";
import {
  memoryRecordings,
  type ContractSnapshot,
  type PartAddress,
  type RecordingDatabase
} from "../recording-store";
import { fakeLocks } from "./catalog-locks";

/**
 * What the base does in each order a review of the one-holder build
 * reproduced. Two keepers on one store and one lock manager are two tabs of
 * the same browser. The form's own steps (Continue, the next part number,
 * run start, row removal) are replicated here with a pointer to the line in
 * the form; they are not exercised through the form.
 */

const CONTRACT: ContractSnapshot = {
  publishedFlowVersion: 4,
  inputFormat: "audio",
  maxFiles: 8,
  maxFileSizeBytes: 10_000_000,
  acceptedMimetypes: ["audio/webm"]
};

const START = Date.UTC(2026, 10, 25, 8, 0, 0);
const STEP = "step-1";
const REC = "rec-1";

function setup() {
  const db = memoryRecordings();
  const locks = fakeLocks();
  /** A form opened in a tab of this browser, by the same person. */
  const tab = () => new RecordingKeeper("flow-1", "user-a", db, locks.locks, () => START);
  return { db, locks, tab };
}

const address = (index: number): PartAddress => ({
  flowId: "flow-1",
  stepId: STEP,
  sessionId: REC,
  index
});

const part = (index: number): JournalPart => ({
  sessionId: REC,
  index,
  mimeType: "audio/webm;codecs=opus",
  capturedAt: START + index * 60_000
});

const audio = (text: string) => new Blob([text], { type: "audio/webm" });

const journal = (keeper: RecordingKeeper) =>
  keeper.journalFor(
    STEP,
    () => CONTRACT,
    () => false
  );

/** A finished part handed over, as `onPart` does (run-recorder.tsx:436). */
const keep = (keeper: RecordingKeeper, index: number, text: string) =>
  keeper.keepPart(STEP, {
    sessionId: REC,
    index,
    blob: audio(text),
    mimeType: "audio/webm",
    durationMs: 1_000,
    capturedAt: START + index * 60_000,
    contract: CONTRACT,
    streamed: false
  });

/**
 * "Continue" as the form does it (run-recorder.tsx:615-630): read the parts,
 * check the step, adopt them. Returns the indices taken over and the next
 * part number the form computes from its rows (run-recorder.tsx:713).
 */
async function continueIn(keeper: RecordingKeeper) {
  const parts = await keeper.readSession(STEP, REC);
  expect(resumeRefusal(CONTRACT, parts)).toBeNull();
  keeper.adopt(STEP, parts);
  return {
    indices: parts.map((stored) => stored.index),
    next: parts.reduce((next, stored) => Math.max(next, stored.index + 1), 0)
  };
}

/** Lets queued journal writes and lock hand-overs land. */
async function settle() {
  for (let round = 0; round < 5; round += 1) await new Promise((resolve) => setTimeout(resolve, 0));
}

/**
 * Exactly what is on the device: parts as `index:bytes` (`*` when rebuilt
 * from a journal), journals by index, chunks as `index/seq:bytes`.
 */
async function device(db: ReturnType<typeof memoryRecordings>) {
  const parts = await Promise.all(
    [...db.parts.values()].map(
      async (stored) =>
        `${stored.index}:${await stored.blob.text()}${stored.interrupted ? "*" : ""}`
    )
  );
  const journals = [...db.journals.values()].map((meta) => meta.index);
  const chunks = await Promise.all(
    [...db.chunks.entries()].map(async ([key, chunk]) => {
      const [, , , index, seq] = key.split("::");
      return `${Number(index)}/${Number(seq)}:${await chunk.blob.text()}`;
    })
  );
  return { parts: parts.sort(), journals: journals.sort(), chunks: chunks.sort() };
}

describe("one holder per kept recording: what the base does in the reviewed orders", () => {
  // build review A review finding F3 (release before the journal's last write): a fix must keep a part whose journal write lands after another form took the recording over; no part number may be given out over it.
  it("base loses: a part whose journal is written after another tab continued is replaced at the same number", async () => {
    const { db, locks, tab } = setup();
    const a = tab();
    expect(await keep(a, 0, "part0")).toBe("device");
    // The browser answers A's lock request for part 1 late (within the journal's 2 s wait).
    locks.holdElsewhere(journalLockName(address(1)));
    const fromA = journal(a);
    fromA.begin(part(1));
    fromA.append(part(1), audio("AAAA"), 1_000);
    // A's form closes mid-part: the recorder leaves the part's journal (recorder.ts:499).
    fromA.leave(part(1));
    await settle();
    expect(await device(db)).toEqual({ parts: ["0:part0"], journals: [], chunks: [] });

    // B opens the form after A closed it: a fresh scan finds no journal yet.
    const b = tab();
    const { saved } = await b.scan(STEP);
    expect(saved.map((recording) => recording.parts)).toEqual([1]);
    expect(await continueIn(b)).toEqual({ indices: [0], next: 1 });

    // A's late lock is granted: its part lands on the device after the hand-over.
    locks.releaseElsewhere(journalLockName(address(1)));
    await settle();
    expect(await device(db)).toEqual({ parts: ["0:part0"], journals: [1], chunks: ["1/0:AAAA"] });

    // B records its part 1 on the same keys and keeps it.
    const fromB = journal(b);
    fromB.begin(part(1));
    fromB.append(part(1), audio("BBBB"), 1_000);
    await settle();
    expect(await keep(b, 1, "BBBB")).toBe("device");
    await settle();
    expect(await device(db)).toEqual({ parts: ["0:part0", "1:BBBB"], journals: [], chunks: [] });
  });

  // build review A review finding F3 (a released recording stays in forgetAll): a fix must let only the form that holds a recording delete it; a form whose discard failed, or that another form took over from, deletes nothing another form added.
  it("base loses: a form whose discard failed later deletes the part another tab added to the recording", async () => {
    const { db, tab } = setup();
    const a = tab();
    expect(await keep(a, 0, "part0")).toBe("device");
    // A throws the recording away (run-recorder.tsx:748) and storage refuses the deletion once.
    const refuse = vi
      .spyOn(db as RecordingDatabase, "deleteSession")
      .mockRejectedValueOnce(new Error("busy"));
    expect(await a.forgetSession(STEP, REC)).toBe(false);
    refuse.mockRestore();
    expect(await device(db)).toEqual({ parts: ["0:part0"], journals: [], chunks: [] });

    // B continues it and keeps a new part.
    const b = tab();
    expect((await b.scan(STEP)).saved.map((recording) => recording.sessionId)).toEqual([REC]);
    expect(await continueIn(b)).toEqual({ indices: [0], next: 1 });
    expect(await keep(b, 1, "BBBB")).toBe("device");
    expect(await device(db)).toEqual({ parts: ["0:part0", "1:BBBB"], journals: [], chunks: [] });

    // A's form starts a run or is closed with its recordings thrown away (start-run-dialog.tsx:310, :284).
    await a.forgetAll();
    expect(await device(db)).toEqual({ parts: [], journals: [], chunks: [] });
  });

  // build review A review finding F7 (a retry gives a refused part the right to be written): a fix must decide per part whether it goes to the device; whatever it decides, part 0's audio stays kept (on the device, or in the tab and uploaded).
  it("base keeps: a part whose journal lock request threw is still stored when the next part began first", async () => {
    const { db, locks, tab } = setup();
    const a = tab();
    const recorder = journal(a);
    locks.failRequests("eneo-flow-recording:");
    recorder.begin(part(0));
    recorder.append(part(0), audio("P0"), 1_000);
    await settle();
    locks.failRequests(null);
    // The recorder starts the next part before it stops the last one (recorder.ts:816).
    recorder.begin(part(1));
    recorder.append(part(1), audio("P1"), 1_000);
    await settle();
    expect(a.degradation(STEP)).toBe("failed");
    expect(await device(db)).toEqual({ parts: [], journals: [1], chunks: ["1/0:P1"] });

    expect(await keep(a, 0, "part0")).toBe("device");
    expect(await keep(a, 1, "part1")).toBe("device");
    await settle();
    expect(await device(db)).toEqual({ parts: ["0:part0", "1:part1"], journals: [], chunks: [] });
  });

  // build review A review finding F10 (run start deletes audio the run did not get): a fix must keep on the device a part the run did not receive because it could not be read in at Continue.
  it("base loses: starting the run deletes a part that could not be read when the recording was continued", async () => {
    const { db, tab } = setup();
    const a = tab();
    expect(await keep(a, 0, "part0")).toBe("device");
    const fromA = journal(a);
    fromA.begin(part(1));
    fromA.append(part(1), audio("AAAA"), 1_000);
    await settle();
    fromA.leave(part(1));
    await settle();
    expect(await device(db)).toEqual({ parts: ["0:part0"], journals: [1], chunks: ["1/0:AAAA"] });

    // B's scan cannot read the journal's chunks this time: the journal stays.
    const b = tab();
    const unreadable = vi
      .spyOn(db as RecordingDatabase, "readChunks")
      .mockRejectedValueOnce(new Error("read"));
    const scanned = await b.scan(STEP);
    unreadable.mockRestore();
    expect(scanned.incomplete).toBe(true);
    expect(scanned.saved.map((recording) => recording.parts)).toEqual([1]);
    expect(await continueIn(b)).toEqual({ indices: [0], next: 1 });
    expect(await device(db)).toEqual({ parts: ["0:part0"], journals: [1], chunks: ["1/0:AAAA"] });

    // The run starts with part 0 only (start-run-dialog.tsx:310).
    await b.forgetAll();
    expect(await device(db)).toEqual({ parts: [], journals: [], chunks: [] });
  });

  // build review A review finding F10 (also a part rebuilt after the upload list was formed): a fix must keep on the device a part rebuilt after Continue that the run did not receive.
  it("base loses: starting the run deletes a part another tab rebuilt after the recording was continued", async () => {
    const { db, tab } = setup();
    const a = tab();
    expect(await keep(a, 0, "part0")).toBe("device");
    const fromA = journal(a);
    fromA.begin(part(1));
    fromA.append(part(1), audio("AAAA"), 1_000);
    await settle();

    // B continues while A still records part 1: its journal is locked and left alone.
    const b = tab();
    expect((await b.scan(STEP)).saved.map((recording) => recording.parts)).toEqual([1]);
    expect(await continueIn(b)).toEqual({ indices: [0], next: 1 });

    // A's tab goes mid-part; the form opened again in A rebuilds part 1.
    fromA.leave(part(1));
    await settle();
    await tab().scan(STEP);
    expect(await device(db)).toEqual({ parts: ["0:part0", "1:AAAA*"], journals: [], chunks: [] });

    // B's run starts with part 0 only (start-run-dialog.tsx:310).
    await b.forgetAll();
    expect(await device(db)).toEqual({ parts: [], journals: [], chunks: [] });
  });

  // build review A review finding F4 (a scan rebuilds the skipped journal before the parts are read): a fix must still take over the rebuilt part and number the next part above it.
  it("base keeps: a part another tab rebuilt between the offer and Continue is continued with the recording", async () => {
    const { db, tab } = setup();
    const a = tab();
    expect(await keep(a, 0, "part0")).toBe("device");
    const fromA = journal(a);
    fromA.begin(part(1));
    fromA.append(part(1), audio("AAAA"), 1_000);
    await settle();

    // B's offer is read while A records part 1.
    const b = tab();
    expect((await b.scan(STEP)).saved.map((recording) => recording.parts)).toEqual([1]);
    // A's tab goes; the form opened again in A rebuilds part 1 before B presses Continue.
    fromA.leave(part(1));
    await settle();
    await tab().scan(STEP);
    expect(await continueIn(b)).toEqual({ indices: [0, 1], next: 2 });

    const fromB = journal(b);
    fromB.begin(part(2));
    fromB.append(part(2), audio("BBBB"), 1_000);
    await settle();
    expect(await keep(b, 2, "BBBB")).toBe("device");
    await settle();
    expect(await device(db)).toEqual({
      parts: ["0:part0", "1:AAAA*", "2:BBBB"],
      journals: [],
      chunks: []
    });
  });

  // build review A review finding F4 (the other order: the rebuild lands after the parts were read): a fix must never give the continuing form a number that a part rebuilt meanwhile holds.
  it("base loses: a part another tab rebuilds after Continue is replaced by the continuing tab's next part", async () => {
    const { db, tab } = setup();
    const a = tab();
    expect(await keep(a, 0, "part0")).toBe("device");
    const fromA = journal(a);
    fromA.begin(part(1));
    fromA.append(part(1), audio("AAAA"), 1_000);
    await settle();

    const b = tab();
    await b.scan(STEP);
    expect(await continueIn(b)).toEqual({ indices: [0], next: 1 });

    fromA.leave(part(1));
    await settle();
    await tab().scan(STEP);
    expect(await device(db)).toEqual({ parts: ["0:part0", "1:AAAA*"], journals: [], chunks: [] });

    const fromB = journal(b);
    fromB.begin(part(1));
    fromB.append(part(1), audio("BBBB"), 1_000);
    await settle();
    expect(await keep(b, 1, "BBBB")).toBe("device");
    await settle();
    expect(await device(db)).toEqual({ parts: ["0:part0", "1:BBBB"], journals: [], chunks: [] });
  });

  // build review A review finding F11 (the number floor covers only numbers seen at takeover): a fix must keep the part recorded again; the removed part's audio may go, since the person took its row off the form.
  it("base keeps: a part recorded after its row was removed takes that number over the removed part whose deletion failed", async () => {
    const { db, tab } = setup();
    const a = tab();
    expect(await keep(a, 0, "part0")).toBe("device");
    expect(await keep(a, 1, "CCCC")).toBe("device");
    // The person removes part 1's row (start-run-dialog.tsx:492) and the deletion fails.
    const refuse = vi
      .spyOn(db as RecordingDatabase, "deletePart")
      .mockRejectedValueOnce(new Error("busy"));
    await a.forgetPart(STEP, REC, 1);
    refuse.mockRestore();
    expect(await device(db)).toEqual({ parts: ["0:part0", "1:CCCC"], journals: [], chunks: [] });

    // The next number comes from the rows: only part 0 is left (run-recorder.tsx:713).
    const recorder = journal(a);
    recorder.begin(part(1));
    recorder.append(part(1), audio("DDDD"), 1_000);
    await settle();
    expect(await keep(a, 1, "DDDD")).toBe("device");
    await settle();
    expect(await device(db)).toEqual({ parts: ["0:part0", "1:DDDD"], journals: [], chunks: [] });
  });
});
