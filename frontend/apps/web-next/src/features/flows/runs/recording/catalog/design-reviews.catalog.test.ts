// @vitest-environment jsdom
/**
 * What today's keeper, journal and store do in each sequence the design
 * passes on "one holder per saved recording" reproduced or traced in the
 * source. Every test is green on today's code and reads the device's bytes
 * back exactly. "base loses" names a loss a fix must remove; "base keeps"
 * names audio no fix may lose.
 */
import { Blob as NodeBlob } from "node:buffer";
import { createElement, useState } from "react";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initializeBrowserSession, SESSION_GENERATION_HEADER } from "@/lib/api/refusal";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp, testAppContext } from "@/test/render";
import { makeFlow } from "../../../flow-fixtures";
import { makeContract, makeInput } from "../../run-fixtures";
import type { RunContract, RunPublic } from "../../runs-api";
import { journalLockName } from "../recording-journal";
import { RecordingKeeper, type JournalPart } from "../recording-keeper";
import {
  memoryRecordings,
  RECORDING_TTL_MS,
  type ContractSnapshot,
  type JournalMeta,
  type StoredPart
} from "../recording-store";
import { fakeLocks } from "./catalog-locks";

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../../../editor/testing/fixtures").apiStub>
}));

// The device's store, as the form finds it.
const device = vi.hoisted(() => ({
  db: null as unknown as ReturnType<typeof import("../recording-store").memoryRecordings>
}));
vi.mock("../recording-store", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../recording-store")>()),
  indexedDbRecordings: () => device.db
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub: makeStub } = await import("../../../editor/testing/fixtures");
  api.stub = makeStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] }));
  return { browserApi: api.stub.client };
});

import { StartRunDialog } from "../../start-run-dialog";

const CONTRACT: ContractSnapshot = {
  publishedFlowVersion: 4,
  inputFormat: "audio",
  maxFiles: 4,
  maxFileSizeBytes: 10_000_000,
  acceptedMimetypes: ["audio/webm"]
};
const START = Date.UTC(2026, 9, 22, 8, 0, 0);
const STEP = "step-1";

/** One browser: a shared store and shared Web Locks; each `tab` is one open run form. */
function setup() {
  const db = memoryRecordings();
  const locks = fakeLocks();
  let now = START;
  const tab = (lockManager: ReturnType<typeof fakeLocks> | null = locks) =>
    new RecordingKeeper("flow-1", "user-a", db, lockManager ? lockManager.locks : null, () => now);
  return {
    db,
    locks,
    tab,
    now: () => now,
    later: (ms: number) => {
      now += ms;
    }
  };
}

/** A finished part as the recorder hands it to `keepPart`. */
const finished = (index: number, audio: string, sessionId = "rec-1", capturedAt?: number) => ({
  sessionId,
  index,
  blob: new Blob([audio], { type: "audio/webm" }),
  mimeType: "audio/webm",
  durationMs: 1_000,
  capturedAt: capturedAt ?? START + index * 60_000,
  contract: CONTRACT,
  streamed: false
});

const live = (
  index: number,
  sessionId = "rec-1",
  mimeType = "audio/webm;codecs=opus"
): JournalPart => ({
  sessionId,
  index,
  mimeType,
  capturedAt: START + index * 60_000
});

const lockOf = (index: number, sessionId = "rec-1") =>
  journalLockName({ flowId: "flow-1", stepId: STEP, sessionId, index });

const journalOf = (keeper: RecordingKeeper) =>
  keeper.journalFor(
    STEP,
    () => CONTRACT,
    () => false
  );

/** What the form does on "Fortsätt inspelningen" today: read, check the step, adopt; the next index. */
async function continueAsForm(keeper: RecordingKeeper, sessionId = "rec-1") {
  const parts = await keeper.readSession(STEP, sessionId);
  keeper.adopt(STEP, parts);
  return parts.reduce((next, part) => Math.max(next, part.index + 1), 0);
}

const text = (blob: Blob): Promise<string> =>
  typeof blob.text === "function"
    ? blob.text()
    : new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.readAsText(blob);
      });

/** The stored parts' audio by "session::index". */
async function stored(db: ReturnType<typeof memoryRecordings>): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  for (const [key, part] of db.parts)
    out[key.replace(`flow-1::${STEP}::`, "")] = await text(part.blob);
  return out;
}

/** The journal chunks' audio by "session::index::seq". */
async function chunks(db: ReturnType<typeof memoryRecordings>): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  for (const [key, chunk] of db.chunks) {
    out[key.replace(`flow-1::${STEP}::`, "")] = await text(chunk.blob);
  }
  return out;
}

function gate() {
  let open = () => {};
  const opened = new Promise<void>((resolve) => {
    open = resolve;
  });
  return { opened, open };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function journalMeta(index: number, sessionId = "rec-1"): JournalMeta {
  return {
    flowId: "flow-1",
    stepId: STEP,
    sessionId,
    index,
    mimeType: "audio/webm",
    capturedAt: START + index * 60_000,
    contract: CONTRACT,
    streamed: false,
    lastChunkAt: START + index * 60_000,
    userId: "user-a"
  };
}

async function leftJournal(
  db: ReturnType<typeof memoryRecordings>,
  index: number,
  audio: string,
  sessionId = "rec-1"
) {
  const meta = journalMeta(index, sessionId);
  await db.putJournal(meta);
  await db.appendChunk(meta, 0, {
    blob: new Blob([audio], { type: "audio/webm" }),
    recordedMs: 1_000,
    at: meta.lastChunkAt
  });
}

describe("plan catalog: what today's keeper does", () => {
  // The file renders the form under jsdom, whose Blob cannot be read back; the keeper's tests use
  // the Blob of Node and of browsers, as the keeper's own tests do.
  beforeEach(() => {
    vi.stubGlobal("Blob", NodeBlob);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  // Review finding plan-1 summary (the original overwrite): a fix must refuse the second form before it can write, so A's part 1 stays "AAAA".
  it("base loses: two forms that continue the same recording write the same part number, and the last one replaces the other's audio", async () => {
    const { db, tab } = setup();
    const a = tab();
    const b = tab();
    expect(await a.keepPart(STEP, finished(0, "A0"))).toBe("device");
    expect((await b.scan(STEP)).saved.map((saved) => saved.sessionId)).toEqual(["rec-1"]);
    const next = await continueAsForm(b);
    expect(next).toBe(1);

    expect(await a.keepPart(STEP, finished(1, "AAAA"))).toBe("device");
    expect(await b.keepPart(STEP, finished(next, "BBBB"))).toBe("device");

    // A still says its part 1 is on the device.
    expect(a.keeping(STEP, "rec-1", 1)).toBe("device");
    expect(await stored(db)).toEqual({ "rec-1::0000": "A0", "rec-1::0001": "BBBB" });
  });

  // Review finding plan-1 (c), plan-2 point 6: without Web Locks a fix keeps today's behaviour as a disclosed limit; it must not lose more than this.
  it("base loses: without Web Locks, two forms that continue the same recording replace each other's part the same way", async () => {
    const { db, tab } = setup();
    const a = tab(null);
    const b = tab(null);
    await a.keepPart(STEP, finished(0, "A0"));
    const next = await continueAsForm(b);
    expect(await a.keepPart(STEP, finished(1, "AAAA"))).toBe("device");
    expect(await b.keepPart(STEP, finished(next, "BBBB"))).toBe("device");
    expect(a.keeping(STEP, "rec-1", 1)).toBe("device");
    expect(await stored(db)).toEqual({ "rec-1::0000": "A0", "rec-1::0001": "BBBB" });
  });

  // Review finding plan-1 F4 and plan-2 point 3 (source map T1): a fix must keep "AAAA" when a tab closes mid-part and another continues from an offer read before the close.
  it("base loses: a tab closes mid-part and another form continues from an earlier offer, so its part takes the same number and the journal's audio is gone", async () => {
    const { db, locks, tab } = setup();
    // A's tab: its own lock manager; the shared one sees its part lock as held elsewhere.
    const a = tab(fakeLocks());
    await a.keepPart(STEP, finished(0, "A0"));
    const ja = journalOf(a);
    ja.begin(live(1));
    ja.append(live(1), new Blob(["AAAA"], { type: "audio/webm" }), 1_000);
    await settle();
    locks.holdElsewhere(lockOf(1));

    const b = tab();
    const offer = await b.scan(STEP);
    expect(offer.incomplete).toBe(false);
    expect(offer.saved[0]).toMatchObject({ sessionId: "rec-1", parts: 1 });
    const next = await continueAsForm(b);
    expect(next).toBe(1);

    // A's tab closes or crashes: the browser lets its lock go, nothing else runs.
    locks.releaseElsewhere(lockOf(1));
    const jb = journalOf(b);
    jb.begin(live(next));
    jb.append(live(next), new Blob(["BBBB"], { type: "audio/webm" }), 1_000);
    await settle();
    expect(await b.keepPart(STEP, finished(next, "BBBB"))).toBe("device");

    expect(await stored(db)).toEqual({ "rec-1::0000": "A0", "rec-1::0001": "BBBB" });
    expect(db.journals.size).toBe(0);
    expect(db.chunks.size).toBe(0);
  });

  // Review finding plan-2 F9: after the holder closed, a new scan before continuing rebuilds the part first; a fix must keep this exact sequence.
  it("base keeps: a scan after the holder closed rebuilds its open part before the other form continues, which numbers after it", async () => {
    const { db, locks, tab } = setup();
    const a = tab(fakeLocks());
    await a.keepPart(STEP, finished(0, "A0"));
    const ja = journalOf(a);
    ja.begin(live(1));
    ja.append(live(1), new Blob(["AAAA"], { type: "audio/webm" }), 1_000);
    await settle();
    locks.holdElsewhere(lockOf(1));
    const b = tab();
    await b.scan(STEP);
    locks.releaseElsewhere(lockOf(1));

    // The form opened again, or "Försök igen": a new scan.
    const again = await b.scan(STEP);
    expect(again.saved[0]).toMatchObject({ sessionId: "rec-1", parts: 2 });
    const next = await continueAsForm(b);
    expect(next).toBe(2);
    expect(await b.keepPart(STEP, finished(next, "BBBB"))).toBe("device");

    expect(await stored(db)).toEqual({
      "rec-1::0000": "A0",
      "rec-1::0001": "AAAA",
      "rec-1::0002": "BBBB"
    });
    expect([...db.parts.values()].map((part) => part.interrupted)).toEqual([false, true, false]);
  });

  // Review finding plan-2 F4 (read order): a fix must establish the rebuilt part before it reads the parts it adopts, so "AAAA" at index 1 is not replaced.
  it("base loses: a form reads the parts, another tab's scan then rebuilds the next part, and the form's next part replaces the rebuilt one", async () => {
    const { db, tab } = setup();
    // A crashed mid-part 1: its journal is on the device, its lock is gone.
    const a = tab(fakeLocks());
    await a.keepPart(STEP, finished(0, "A0"));
    const ja = journalOf(a);
    ja.begin(live(1));
    ja.append(live(1), new Blob(["AAAA"], { type: "audio/webm" }), 1_000);
    await settle();

    const b = tab();
    const parts = await b.readSession(STEP, "rec-1");
    expect(parts.map((part) => part.index)).toEqual([0]);

    const c = tab();
    await c.scan(STEP);
    expect(await stored(db)).toEqual({ "rec-1::0000": "A0", "rec-1::0001": "AAAA" });

    b.adopt(STEP, parts);
    expect(await b.keepPart(STEP, finished(1, "BBBB"))).toBe("device");
    expect(await stored(db)).toEqual({ "rec-1::0000": "A0", "rec-1::0001": "BBBB" });
  });

  // Review finding plan-1 F1 (and plan-2 F1 for another recording): not a loss; a fix that makes discard final may drop these bytes, but must not drop any recording the person did not discard.
  it("base keeps: a scan paused while it rebuilds a part writes the part back after another tab discarded the recording", async () => {
    const { db, tab } = setup();
    const a = tab();
    await a.keepPart(STEP, finished(0, "A0"));
    const ja = journalOf(a);
    ja.begin(live(1));
    ja.append(live(1), new Blob(["a"], { type: "audio/webm" }), 1_000);
    ja.append(live(1), new Blob(["b"], { type: "audio/webm" }), 2_000);
    await settle();
    // C's offer came while A still recorded part 1.
    const c = tab();
    expect((await c.scan(STEP)).saved[0]).toMatchObject({ parts: 1 });
    ja.leave(live(1));
    await settle();

    const paused = gate();
    const readChunks = db.readChunks;
    const spy = vi.spyOn(db, "readChunks").mockImplementationOnce(async (address) => {
      const read = await readChunks(address);
      await paused.opened;
      return read;
    });
    const b = tab();
    const scanning = b.scan(STEP);
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());

    expect(await c.forgetSession(STEP, "rec-1")).toBe(true);
    expect(db.parts.size).toBe(0);

    paused.open();
    const result = await scanning;
    expect(await stored(db)).toEqual({ "rec-1::0001": "ab" });
    expect([...db.parts.values()][0]!.interrupted).toBe(true);
    expect(result.saved[0]).toMatchObject({ sessionId: "rec-1", parts: 1 });
    expect(db.journals.size).toBe(0);
  });

  // Review finding plan-1 F2 and plan-2 F2: a fix must re-read activity before it deletes by age, so the fresh "A1" the form says is on the device stays.
  it("base loses: a scan deletes by age from a parts list read before a fresh part was saved, and the fresh part goes too", async () => {
    const { db, tab, later, now } = setup();
    const a = tab();
    await a.keepPart(STEP, finished(0, "A0"));
    later(RECORDING_TTL_MS + 2_000);

    const paused = gate();
    const listParts = db.listParts;
    const spy = vi.spyOn(db, "listParts").mockImplementationOnce(async (flowId, stepId) => {
      const read = await listParts(flowId, stepId);
      await paused.opened;
      return read;
    });
    const s = tab();
    const scanning = s.scan(STEP);
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());

    expect(await a.keepPart(STEP, finished(1, "A1", "rec-1", now()))).toBe("device");
    expect(await stored(db)).toEqual({ "rec-1::0000": "A0", "rec-1::0001": "A1" });

    paused.open();
    expect((await scanning).saved).toEqual([]);
    expect(a.keeping(STEP, "rec-1", 1)).toBe("device");
    expect(await stored(db)).toEqual({});
  });

  // Review finding plan-1 F3 (late part cleanup): a fix must let a discard's pending part write end before another form may write, so "BBBB" stays.
  it("base loses: a discard reports done while a part it handed over is still being stored, and that part's late cleanup deletes another form's part at the same number", async () => {
    const { db, tab } = setup();
    const a = tab();
    await a.keepPart(STEP, finished(0, "A0"));
    const b = tab();
    expect(await continueAsForm(b)).toBe(1);

    const paused = gate();
    const putPart = db.putPart;
    vi.spyOn(db, "putPart").mockImplementationOnce(async (part) => {
      await putPart(part);
      await paused.opened;
    });
    const keepingA = a.keepPart(STEP, finished(1, "AAAA"));
    await vi.waitFor(() => expect(db.parts.size).toBe(2));

    expect(await a.forgetSession(STEP, "rec-1")).toBe(true);
    expect(db.parts.size).toBe(0);
    expect(await b.keepPart(STEP, finished(1, "BBBB"))).toBe("device");
    expect(await stored(db)).toEqual({ "rec-1::0001": "BBBB" });

    paused.open();
    expect(await keepingA).toBe("tab");
    expect(b.keeping(STEP, "rec-1", 1)).toBe("device");
    expect(await stored(db)).toEqual({});
  });

  // Review finding plan-1 F3 (stale cleanup): a fix must take a failed discard's recording out of what the form later cleans up, so "A0" and "B1" stay.
  it("base loses: a discard fails, another form continues and records more, and the first form's cleanup then deletes every part", async () => {
    const { db, tab } = setup();
    const a = tab();
    await a.keepPart(STEP, finished(0, "A0"));
    vi.spyOn(db, "deleteSession").mockRejectedValueOnce(new Error("blocked"));
    expect(await a.forgetSession(STEP, "rec-1")).toBe(false);
    expect(await stored(db)).toEqual({ "rec-1::0000": "A0" });

    const b = tab();
    expect((await b.scan(STEP)).saved).toHaveLength(1);
    const next = await continueAsForm(b);
    expect(await b.keepPart(STEP, finished(next, "B1"))).toBe("device");

    // The first form closes confirmed, or its run starts.
    await a.forgetAll();
    expect(b.keeping(STEP, "rec-1", 0)).toBe("device");
    expect(b.keeping(STEP, "rec-1", 1)).toBe("device");
    expect(await stored(db)).toEqual({});
  });

  // Review finding plan-1 F3 and answer (a) (cleanup at run start or confirmed close): a fix must clean up only what this form still holds, so "B1", which the run did not get, stays.
  it("base loses: a form starts its run and its cleanup deletes the part another form added to the same recording", async () => {
    const { db, tab } = setup();
    const a = tab();
    await a.keepPart(STEP, finished(0, "A0"));
    const b = tab();
    const next = await continueAsForm(b);
    expect(await b.keepPart(STEP, finished(next, "B1"))).toBe("device");

    await a.forgetAll();
    expect(b.keeping(STEP, "rec-1", 1)).toBe("device");
    expect(await stored(db)).toEqual({});
  });

  // Review finding plan-2 F7 (as base does it, with no hold): a fix must refuse a discard from a form that does not hold the recording, so "A0" stays.
  it("base loses: another tab discards a recording an open form still says is kept on the device", async () => {
    const { db, tab } = setup();
    const a = tab();
    await a.keepPart(STEP, finished(0, "A0"));
    const b = tab();
    expect((await b.scan(STEP)).saved).toHaveLength(1);
    expect(await b.forgetSession(STEP, "rec-1")).toBe(true);
    expect(a.keeping(STEP, "rec-1", 0)).toBe("device");
    expect(await stored(db)).toEqual({});
  });

  // Review finding plan-2 F8: MP4 and Ogg journal nothing, so a fix must never send the person to close the holder's tab mid-part; the open part is nowhere on the device.
  it("base loses: an MP4 or Ogg part being recorded is nowhere on the device, so closing its tab loses it", async () => {
    for (const mimeType of ["audio/mp4", "audio/ogg;codecs=opus"]) {
      const { db, tab } = setup();
      const a = tab();
      await a.keepPart(STEP, finished(0, "A0"));
      const ja = journalOf(a);
      ja.begin(live(1, "rec-1", mimeType));
      ja.append(live(1, "rec-1", mimeType), new Blob(["AAAA"], { type: mimeType }), 1_000);
      await settle();
      expect(a.degradation(STEP)).toBe("unavailable");

      // The tab closes: another form finds only the finished part.
      const scan = await tab().scan(STEP);
      expect(scan).toMatchObject({ incomplete: false });
      expect(scan.saved[0]).toMatchObject({ sessionId: "rec-1", parts: 1 });
      expect(await stored(db)).toEqual({ "rec-1::0000": "A0" });
      expect(db.journals.size).toBe(0);
      expect(db.chunks.size).toBe(0);
    }
  });

  // Review finding plan-2 (assumption: no Web Locks and a journal from an earlier context): a fix must not let a lockless form take the journal's number, so "AAAA" survives the later scan.
  it("base loses: a form without Web Locks continues past a journal left by an earlier page, takes its number, and the next scan with locks drops the journal's audio", async () => {
    const { db, tab } = setup();
    const a = tab();
    await a.keepPart(STEP, finished(0, "A0"));
    const ja = journalOf(a);
    ja.begin(live(1));
    ja.append(live(1), new Blob(["AAAA"], { type: "audio/webm" }), 1_000);
    ja.leave(live(1));
    await settle();

    const b = tab(null);
    const scan = await b.scan(STEP);
    expect(scan).toMatchObject({ incomplete: false });
    expect(scan.saved[0]).toMatchObject({ parts: 1 });
    expect(await chunks(db)).toEqual({ "rec-1::0001::000000": "AAAA" });
    const next = await continueAsForm(b);
    expect(next).toBe(1);
    journalOf(b).begin(live(next));
    expect(await b.keepPart(STEP, finished(next, "BBBB"))).toBe("device");
    expect(await chunks(db)).toEqual({ "rec-1::0001::000000": "AAAA" });

    await tab().scan(STEP);
    expect(await stored(db)).toEqual({ "rec-1::0000": "A0", "rec-1::0001": "BBBB" });
    expect(db.journals.size).toBe(0);
    expect(db.chunks.size).toBe(0);
  });

  // Review finding plan-2 F4 (expiry is not recovery): by design (the day limit); a fix must not read a journal's disappearance as its part being rebuilt.
  it("base loses: a journal idle for over a day is dropped with its audio and leaves no part", async () => {
    const { db, tab, later } = setup();
    const a = tab();
    const ja = journalOf(a);
    ja.begin(live(0));
    ja.append(live(0), new Blob(["AAAA"], { type: "audio/webm" }), 1_000);
    ja.leave(live(0));
    await settle();
    expect(await chunks(db)).toEqual({ "rec-1::0000::000000": "AAAA" });
    later(RECORDING_TTL_MS + 2_000);

    expect(await tab().scan(STEP)).toEqual({ saved: [], incomplete: false });
    expect(await stored(db)).toEqual({});
    expect(db.journals.size).toBe(0);
    expect(db.chunks.size).toBe(0);
  });

  // Review finding plan-1 F4 (partial recovery): a fix must keep what a recovery already rebuilt and retry the rest; "a" and then "b" both end as parts.
  it("base keeps: a recovery that rebuilds one journal and cannot read the next keeps the first part and leaves the second journal for another try", async () => {
    const { db, tab } = setup();
    await leftJournal(db, 1, "a");
    await leftJournal(db, 2, "b");
    const readChunks = db.readChunks;
    const spy = vi
      .spyOn(db, "readChunks")
      .mockImplementation(async (address) => (address.index === 2 ? null : readChunks(address)));

    const first = await tab().scan(STEP);
    expect(first.incomplete).toBe(true);
    expect(await stored(db)).toEqual({ "rec-1::0001": "a" });
    expect([...db.journals.keys()]).toEqual(["flow-1::step-1::rec-1::0002"]);
    expect(await chunks(db)).toEqual({ "rec-1::0002::000000": "b" });

    spy.mockRestore();
    const second = await tab().scan(STEP);
    expect(second.incomplete).toBe(false);
    expect(await stored(db)).toEqual({ "rec-1::0001": "a", "rec-1::0002": "b" });
    expect(db.journals.size).toBe(0);
  });

  // Review finding plan-1 F4 (a step-wide result): a fix must not refuse or drop the target because another recording's journal cannot be read; both stay.
  it("base keeps: an unreadable journal of another recording marks the scan incomplete, stays as it is, and the target is still offered and read", async () => {
    const { db, tab } = setup();
    await tab().keepPart(STEP, finished(0, "A0"));
    await leftJournal(db, 0, "other", "rec-2");
    vi.spyOn(db, "readChunks").mockResolvedValue(null);

    const b = tab();
    const scan = await b.scan(STEP);
    expect(scan.incomplete).toBe(true);
    expect(scan.saved.map((saved) => saved.sessionId)).toEqual(["rec-1"]);
    expect(await continueAsForm(b)).toBe(1);
    expect(await stored(db)).toEqual({ "rec-1::0000": "A0" });
    expect(await chunks(db)).toEqual({ "rec-2::0000::000000": "other" });
  });

  // Review finding plan-2 F1 and F2 (Continue as a new trigger): a fix must not make continuing rebuild or expire other recordings; today it reads parts only.
  it("base keeps: continuing reads the recording's parts only and leaves every journal of the step as it was", async () => {
    const { db, tab } = setup();
    await tab().keepPart(STEP, finished(0, "A0"));
    await leftJournal(db, 0, "other", "rec-2");
    const b = tab();
    expect(await continueAsForm(b)).toBe(1);
    expect(await stored(db)).toEqual({ "rec-1::0000": "A0" });
    expect([...db.journals.keys()]).toEqual(["flow-1::step-1::rec-2::0000"]);
    expect(await chunks(db)).toEqual({ "rec-2::0000::000000": "other" });
  });

  // Review finding plan-1 (b) and plan-2 (no lock cycle): a fix must keep two concurrent scans from deadlocking or rebuilding a part twice.
  it("base keeps: two tabs scanning at once rebuild a left part exactly once", async () => {
    const { db, tab } = setup();
    const a = tab();
    const ja = journalOf(a);
    ja.begin(live(0));
    ja.append(live(0), new Blob(["ab"], { type: "audio/webm" }), 1_000);
    ja.leave(live(0));
    await settle();

    const putPart = vi.spyOn(db, "putPart");
    const [first, second] = await Promise.all([tab().scan(STEP), tab().scan(STEP)]);
    expect(putPart).toHaveBeenCalledTimes(1);
    expect(first.saved).toHaveLength(1);
    expect(second.saved).toHaveLength(1);
    expect(await stored(db)).toEqual({ "rec-1::0000": "ab" });
    expect(db.journals.size).toBe(0);
  });

  // Review finding plan-1 (c) and plan-2 F7 (a lock request that throws): a fix must not turn a throwing request into a lost part; today the part is stored when it ends.
  it("base keeps: a part whose journal lock request throws is not journaled, and is stored on the device when it ends", async () => {
    const { db, locks, tab } = setup();
    locks.failRequests("eneo-flow-recording:");
    const a = tab();
    const ja = journalOf(a);
    ja.begin(live(0));
    ja.append(live(0), new Blob(["a"], { type: "audio/webm" }), 1_000);
    await settle();
    expect(a.degradation(STEP)).toBe("failed");
    expect(await a.keepPart(STEP, finished(0, "A0"))).toBe("device");
    locks.failRequests(null);
    expect(await stored(db)).toEqual({ "rec-1::0000": "A0" });
    expect(db.journals.size).toBe(0);
    expect(db.chunks.size).toBe(0);
  });

  // Review finding plan-1 (b) and plan-2 F7 (a recovery lock request that throws): a fix must leave the journal for another try, as today.
  it("base keeps: a scan whose recovery lock request throws says it is incomplete and leaves the journal for the next scan", async () => {
    const { db, locks, tab } = setup();
    await leftJournal(db, 0, "ab");
    locks.failRequests("eneo-flow-recovery:");
    expect(await tab().scan(STEP)).toEqual({ saved: [], incomplete: true });
    expect(await chunks(db)).toEqual({ "rec-1::0000::000000": "ab" });

    locks.failRequests(null);
    expect((await tab().scan(STEP)).saved).toHaveLength(1);
    expect(await stored(db)).toEqual({ "rec-1::0000": "ab" });
  });

  // Review finding plan-1 verification (handoff after "Spara och fortsätt senare", same tab or another): a fix must keep every part across the handoff.
  it("base keeps: a recording saved for later and continued by a new form keeps every part, numbered after the saved ones", async () => {
    const { db, tab } = setup();
    const a = tab();
    await a.keepPart(STEP, finished(0, "A0"));
    await a.keepPart(STEP, finished(1, "A1"));
    // The form closes with "Spara och fortsätt senare"; a new form opens.
    const b = tab();
    expect((await b.scan(STEP)).saved[0]).toMatchObject({ parts: 2 });
    const next = await continueAsForm(b);
    expect(next).toBe(2);
    const jb = journalOf(b);
    jb.begin(live(next));
    jb.append(live(next), new Blob(["B2"], { type: "audio/webm" }), 1_000);
    await settle();
    expect(await b.keepPart(STEP, finished(next, "B2"))).toBe("device");
    expect(await stored(db)).toEqual({
      "rec-1::0000": "A0",
      "rec-1::0001": "A1",
      "rec-1::0002": "B2"
    });
    expect(db.journals.size).toBe(0);
  });
});

/* ---------- Through the form: which offer a press is aimed at ---------- */

class FakeUpload {
  static sent: File[] = [];
  status = 0;
  responseText = "";
  upload = { onprogress: null as ((event: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  getAllResponseHeaders() {
    return `${SESSION_GENERATION_HEADER}: session-a\r\n`;
  }
  abort() {}
  send(body: FormData) {
    const file = body.get("upload_file") as File;
    queueMicrotask(() => {
      FakeUpload.sent.push(file);
      this.status = 201;
      this.responseText = JSON.stringify({
        id: `file-${FakeUpload.sent.length}`,
        name: file.name,
        mimetype: file.type,
        size: file.size
      });
      this.onload?.();
    });
  }
}

class FakeMediaRecorder {
  static isTypeSupported = (type: string) => type === "audio/webm;codecs=opus";
  state: RecordingState = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: ((event: Event) => void) | null = null;
  onerror: (() => void) | null = null;
  start() {
    this.state = "recording";
  }
  pause() {
    this.state = "paused";
  }
  resume() {
    this.state = "recording";
  }
  requestData() {
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
  }
  stop() {
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
    this.state = "inactive";
    queueMicrotask(() => this.onstop?.(new Event("stop")));
  }
}

const microphone = vi.fn<() => Promise<MediaStream>>();

function installBrowser() {
  Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: microphone }
  });
  const track = Object.assign(new EventTarget(), { stop: vi.fn() });
  microphone.mockResolvedValue({
    getTracks: () => [track],
    getAudioTracks: () => [track]
  } as unknown as MediaStream);
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  vi.stubGlobal("AudioContext", undefined);
  Object.defineProperty(navigator, "locks", { configurable: true, value: fakeLocks().locks });
}

const KEPT_BASE = Math.floor(Date.now() / 60_000) * 60_000 - 2 * 60 * 60 * 1000;
const WEBM = "0a1b2c3d-0000-4000-8000-000000000001";
const OGG = "0a1b2c3d-0000-4000-8000-000000000002";

function keptPart(index: number, overrides: Partial<StoredPart> = {}): StoredPart {
  return {
    flowId: "flow-1",
    stepId: STEP,
    sessionId: WEBM,
    index,
    blob: new Blob([`part ${index}`], { type: "audio/webm" }),
    mimeType: "audio/webm",
    durationMs: 30_000,
    capturedAt: KEPT_BASE + index * 60_000,
    interrupted: false,
    contract: {
      publishedFlowVersion: 4,
      inputFormat: "audio",
      maxFiles: 4,
      maxFileSizeBytes: null,
      acceptedMimetypes: ["audio/webm", "audio/mp4"]
    },
    streamed: false,
    userId: "user-1",
    ...overrides
  };
}

const audioContract = (): RunContract =>
  makeContract({
    published_flow_version: 4,
    steps_requiring_input: [
      makeInput({
        step_id: STEP,
        label: "Mötet",
        input_format: "audio",
        accepted_mimetypes: ["audio/webm", "audio/mp4"],
        max_files: 4,
        max_duration_seconds: 7_200,
        max_recording_seconds: 7_200,
        recording_part_seconds: 1_800
      })
    ],
    transcription: {
      live: { available: false, reason: "model_not_realtime" },
      single_recording: true,
      max_speakers: null,
      speaker_labels: {
        default: false,
        required: false,
        selectable: false,
        unavailable_reason: null
      }
    }
  });

function Harness({ onStarted }: { onStarted: (run: RunPublic) => void }) {
  const [open, setOpen] = useState(false);
  return createElement(
    "div",
    null,
    createElement("button", { type: "button", onClick: () => setOpen(true) }, "Kör"),
    createElement(StartRunDialog, {
      flow: makeFlow({ published_version: 4 }),
      open,
      onOpenChange: setOpen,
      onStarted
    })
  );
}

async function openDialog() {
  api.routes["GET /api/v1/flows/{id}/run-contract/"] = () => ({ body: audioContract() });
  renderInApp(createElement(Harness, { onStarted: vi.fn() }), {
    appContext: testAppContext({ user: { id: "user-1" } })
  });
  fireEvent.click(screen.getByRole("button", { name: "Kör" }));
  const dialog = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
  await within(dialog).findByText(/^Mötet/);
  return dialog;
}

const button = (dialog: HTMLElement, name: string) => within(dialog).getByRole("button", { name });

async function deviceParts(): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  for (const [key, part] of device.db.parts)
    out[key.replace(`flow-1::${STEP}::`, "")] = await text(part.blob);
  return out;
}

describe("plan catalog: what today's form aims a press at", () => {
  beforeEach(async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(null, { status: 204, headers: { [SESSION_GENERATION_HEADER]: "session-a" } })
        )
    );
    await initializeBrowserSession();
    vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:${crypto.randomUUID()}`);
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    api.routes = {};
    FakeUpload.sent = [];
    microphone.mockReset();
    vi.stubGlobal("XMLHttpRequest", FakeUpload);
    device.db = memoryRecordings();
  });

  afterEach(() => {
    cleanup();
    api.stub.calls.length = 0;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  // Review finding plan-1 F5: a refused offer must keep its refusal and its Discard on the recording it concerns, so the other recording ("part 0" of the WebM one) stays and is offered next.
  it("base keeps: a refused offer stays in place with its refusal, Discard removes only that recording, and the other kept recording is offered next", async () => {
    installBrowser();
    await device.db.putPart(
      keptPart(0, {
        sessionId: OGG,
        mimeType: "audio/ogg",
        blob: new Blob(["ogg 0"], { type: "audio/ogg" }),
        capturedAt: KEPT_BASE + 30 * 60_000
      })
    );
    await device.db.putPart(keptPart(0));
    const dialog = await openDialog();

    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    expect(
      await within(dialog).findByText(messages.flow_transcript_resume_type_not_accepted)
    ).toBeTruthy();
    expect(FakeUpload.sent).toHaveLength(0);

    fireEvent.click(button(dialog, messages.flow_transcript_resume_discard));
    await waitFor(() => expect(device.db.parts.size).toBe(1));
    expect(await deviceParts()).toEqual({ [`${WEBM}::0000`]: "part 0" });

    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    expect(await within(dialog).findByText("Inspelning, del 1 (00:30)")).toBeTruthy();
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    expect(FakeUpload.sent[0]!.name).toMatch(new RegExp(`^recording-${WEBM}-seg00-`));
  });

  // Review finding plan-1 F5 and verification (the form that is not offered a recording can still record): a fix must keep a fresh recording possible next to an unanswered offer, and the kept one intact.
  it("base keeps: with an offer unanswered, recording starts a new recording and the kept one stays as it was", async () => {
    installBrowser();
    await device.db.putPart(keptPart(0));
    const dialog = await openDialog();
    expect(await within(dialog).findByText(messages.flow_transcript_resume_title)).toBeTruthy();

    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 1/);
    await waitFor(() => expect(device.db.parts.size).toBe(2));

    const parts = await deviceParts();
    expect(parts[`${WEBM}::0000`]).toBe("part 0");
    const fresh = Object.keys(parts).filter((key) => !key.startsWith(WEBM));
    expect(fresh).toHaveLength(1);
    expect(fresh[0]).toMatch(/::0000$/);
    expect(within(dialog).getByText(messages.flow_transcript_resume_title)).toBeTruthy();
  });
});
