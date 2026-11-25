import { describe, expect, it, vi } from "vitest";
import { JOURNAL_MAX_PENDING_CHUNKS } from "./recording-journal";
import {
  contractSnapshot,
  RecordingKeeper,
  resumeRefusal,
  storedPartFile,
  type JournalPart
} from "./recording-keeper";
import {
  memoryRecordings,
  RECORDING_TTL_MS,
  type ContractSnapshot,
  type JournalMeta
} from "./recording-store";
import { fakeLocks } from "./testing/fake-locks";

const CONTRACT: ContractSnapshot = {
  publishedFlowVersion: 4,
  inputFormat: "audio",
  maxFiles: 4,
  maxFileSizeBytes: 10_000_000,
  acceptedMimetypes: ["audio/webm"]
};

const START = Date.UTC(2026, 9, 22, 8, 0, 0);

function setup({ locks = true } = {}) {
  const db = memoryRecordings();
  const lockManager = fakeLocks();
  let now = START;
  /** The form as a person opens it in this browser; null while their id is not known. */
  const as = (userId: string | null) =>
    new RecordingKeeper("flow-1", userId, db, locks ? lockManager.locks : null, () => now);
  return {
    db,
    keeper: as("user-a"),
    as,
    lockManager,
    later: (ms: number) => {
      now += ms;
    }
  };
}

const part = (index: number, sessionId = "rec-1"): JournalPart => ({
  sessionId,
  index,
  mimeType: "audio/webm;codecs=opus",
  capturedAt: START + index * 60_000
});

/** Lets the journal's queued writes land. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("RecordingKeeper", () => {
  it("keeps a finished part on the device and offers its recording to continue", async () => {
    const { keeper, db } = setup();
    const kept = await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["audio"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      durationMs: 90_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });

    expect(kept).toBe("device");
    expect(keeper.keeping("step-1", "rec-1", 0)).toBe("device");
    expect(db.parts.size).toBe(1);
    const { saved, incomplete } = await keeper.scan("step-1");
    expect(incomplete).toBe(false);
    expect(saved).toEqual([
      {
        sessionId: "rec-1",
        parts: 1,
        durationMs: 90_000,
        startedAt: START,
        interruptedAt: null,
        contract: CONTRACT
      }
    ]);
    const [stored] = await keeper.readSession("step-1", "rec-1");
    expect(storedPartFile(stored!).name).toBe(
      "recording-rec-1-seg00-2026-10-22T08-00-00-000Z.webm"
    );
  });

  it("rebuilds the part the page left mid-recording from its journal", async () => {
    const { keeper, db } = setup();
    const journal = keeper.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(1));
    journal.append(part(1), new Blob(["a"], { type: "audio/webm" }), 1_000);
    journal.append(part(1), new Blob(["b"], { type: "audio/webm" }), 2_000);
    journal.leave(part(1));
    await settle();
    expect(db.chunks.size).toBe(2);

    const { saved } = await keeper.scan("step-1");
    expect(saved[0]).toMatchObject({
      sessionId: "rec-1",
      parts: 1,
      durationMs: 2_000,
      interruptedAt: START + 60_000 + 2_000
    });
    const [rebuilt] = await keeper.readSession("step-1", "rec-1");
    expect(rebuilt).toMatchObject({ index: 1, interrupted: true, durationMs: 2_000 });
    expect(await rebuilt!.blob.text()).toBe("ab");
    // The journal is gone once the part is stored.
    expect(db.journals.size).toBe(0);
    expect(db.chunks.size).toBe(0);
  });

  it("keeps whether a part was streamed, also for a part rebuilt from its journal", async () => {
    const { keeper } = setup();
    const journal = keeper.journalFor(
      "step-1",
      () => CONTRACT,
      () => true
    );
    journal.begin(part(0));
    journal.append(part(0), new Blob(["a"], { type: "audio/webm" }), 1_000);
    journal.leave(part(0));
    await settle();
    await keeper.scan("step-1");
    const [rebuilt] = await keeper.readSession("step-1", "rec-1");
    expect(rebuilt).toMatchObject({ interrupted: true, streamed: true });
  });

  it("keeps the stored live transcript with the parts it stands for, once they are stored", async () => {
    const { keeper } = setup();
    const keep = (index: number) =>
      keeper.keepPart("step-1", {
        sessionId: "rec-1",
        index,
        blob: new Blob(["audio"], { type: "audio/webm" }),
        mimeType: "audio/webm",
        durationMs: 1_000,
        capturedAt: START,
        contract: CONTRACT,
        streamed: true
      });
    void keep(0);
    void keep(1);
    await keeper.keepLiveTranscript(
      "step-1",
      [
        { sessionId: "rec-1", index: 0 },
        { sessionId: "rec-1", index: 1 }
      ],
      "tr-1"
    );
    const parts = await keeper.readSession("step-1", "rec-1");
    expect(parts.map((stored) => stored.liveTranscript)).toEqual([
      { id: "tr-1", parts: 2 },
      { id: "tr-1", parts: 2 }
    ]);
  });

  it("keeps no live transcript when a part it stands for is not on the device", async () => {
    const { keeper, db } = setup();
    vi.spyOn(db, "putPart").mockRejectedValueOnce(new Error("QuotaExceededError"));
    const keep = (index: number) =>
      keeper.keepPart("step-1", {
        sessionId: "rec-1",
        index,
        blob: new Blob(["audio"], { type: "audio/webm" }),
        mimeType: "audio/webm",
        durationMs: 1_000,
        capturedAt: START,
        contract: CONTRACT,
        streamed: true
      });
    void keep(0);
    void keep(1);
    await keeper.keepLiveTranscript(
      "step-1",
      [
        { sessionId: "rec-1", index: 0 },
        { sessionId: "rec-1", index: 1 }
      ],
      "tr-1"
    );
    const parts = await keeper.readSession("step-1", "rec-1");
    expect(parts).toHaveLength(1);
    expect(parts[0]).toMatchObject({ streamed: true });
    expect(parts[0]!.liveTranscript).toBeUndefined();
  });

  it("drops the journal of a part that was stored", async () => {
    const { keeper, db } = setup();
    const journal = keeper.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(0));
    journal.append(part(0), new Blob(["a"]), 1_000);
    await settle();
    await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["whole"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    expect(db.journals.size).toBe(0);
    expect(db.chunks.size).toBe(0);
  });

  it("leaves alone a part another tab still records", async () => {
    const { keeper, db, lockManager } = setup();
    const journal = keeper.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(0));
    journal.append(part(0), new Blob(["a"]), 1_000);
    await settle();

    // This tab holds the part's lock while it records: the scan does not take it.
    expect((await keeper.scan("step-1")).saved).toEqual([]);
    expect(db.journals.size).toBe(1);

    journal.leave(part(0));
    await settle();
    lockManager.holdElsewhere("eneo-flow-recording:flow-1::step-1::rec-1::0000");
    expect((await keeper.scan("step-1")).saved).toEqual([]);
    lockManager.releaseElsewhere("eneo-flow-recording:flow-1::step-1::rec-1::0000");
    expect((await keeper.scan("step-1")).saved).toHaveLength(1);
  });

  it("journals nothing without Web Locks, or for audio a cut-off file of which would not play", async () => {
    const withoutLocks = setup({ locks: false });
    withoutLocks.keeper
      .journalFor(
        "step-1",
        () => CONTRACT,
        () => false
      )
      .begin(part(0));
    expect(withoutLocks.keeper.degradation("step-1")).toBe("unavailable");

    const mp4 = setup();
    mp4.keeper
      .journalFor(
        "step-1",
        () => CONTRACT,
        () => false
      )
      .begin({ ...part(0), mimeType: "audio/mp4" });
    expect(mp4.keeper.degradation("step-1")).toBe("unavailable");
    expect(mp4.db.journals.size).toBe(0);
  });

  it("says when storage falls behind, and keeps what it wrote", async () => {
    const { keeper, db } = setup();
    const appendChunk = vi.spyOn(db, "appendChunk").mockReturnValue(new Promise(() => undefined));
    const journal = keeper.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(0));
    for (let chunk = 0; chunk <= JOURNAL_MAX_PENDING_CHUNKS + 1; chunk += 1) {
      journal.append(part(0), new Blob(["a"]), chunk * 1_000);
    }
    expect(keeper.degradation("step-1")).toBe("failed");
    appendChunk.mockRestore();
  });

  it("says a part is kept only in this tab when storage refuses it", async () => {
    const { keeper, db } = setup();
    vi.spyOn(db, "putPart").mockRejectedValue(new Error("QuotaExceededError"));
    const kept = await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["audio"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    expect(kept).toBe("tab");
    expect(keeper.keeping("step-1", "rec-1", 0)).toBe("tab");
  });

  it("forgets a recording thrown away: its parts, its journal and parts handed over late", async () => {
    const { keeper, db } = setup();
    const journal = keeper.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["audio"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    journal.begin(part(1));
    journal.append(part(1), new Blob(["a"]), 1_000);
    expect(keeper.holdsSessions).toBe(true);

    await keeper.forgetAll();
    // The recorder lets go after the form: what it left is not kept either.
    journal.leave(part(1));
    await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 1,
      blob: new Blob(["late"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    await settle();
    expect(db.parts.size).toBe(0);
    expect(db.journals.size).toBe(0);
    expect(db.chunks.size).toBe(0);
  });

  it("deletes a recording with no activity for a day", async () => {
    const { keeper, db, later } = setup();
    await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["audio"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    later(RECORDING_TTL_MS + 2_000);
    expect((await keeper.scan("step-1")).saved).toEqual([]);
    expect(db.parts.size).toBe(0);
  });

  it("keeps a recording continued just before its day ran out: its new journal counts", async () => {
    const { keeper, db, later } = setup();
    await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["audio"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    later(RECORDING_TTL_MS + 2_000);
    // The recording goes on: its next part is being recorded and journaled now.
    const journal = keeper.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(1));
    journal.append(part(1), new Blob(["a"], { type: "audio/webm" }), 1_000);
    await settle();

    await keeper.scan("step-1");
    expect(db.parts.size).toBe(1);
    expect(db.journals.size).toBe(1);
    expect(db.chunks.size).toBe(1);
  });

  it("deletes a recording whose parts and journal are all older than a day", async () => {
    const { keeper, as, db, later, lockManager } = setup();
    await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["audio"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    const journal = keeper.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(1));
    journal.append(part(1), new Blob(["a"], { type: "audio/webm" }), 1_000);
    journal.leave(part(1));
    await settle();
    // A tab left it without letting go: the journal is not rebuilt, only aged.
    lockManager.holdElsewhere("eneo-flow-recording:flow-1::step-1::rec-1::0001");
    later(RECORDING_TTL_MS + 120_000);

    await as("user-a").scan("step-1");
    expect(db.parts.size).toBe(0);
    expect(db.journals.size).toBe(0);
    expect(db.chunks.size).toBe(0);
  });

  it("deletes nothing when the journals could not be read", async () => {
    const { keeper, db, later } = setup();
    await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["audio"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    later(RECORDING_TTL_MS + 2_000);
    vi.spyOn(db, "listJournals").mockRejectedValue(new Error("blocked"));

    expect(await keeper.scan("step-1")).toEqual({ saved: [], incomplete: true });
    expect(db.parts.size).toBe(1);
  });

  it("offers a kept recording only to the person who recorded it", async () => {
    const { keeper, as, db } = setup();
    await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["audio"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    expect([...db.parts.values()][0]).toMatchObject({ userId: "user-a" });

    // Someone else signs in on the same browser: nothing to continue, read or rebuild.
    const other = as("user-b");
    expect(await other.scan("step-1")).toEqual({ saved: [], incomplete: false });
    expect(await other.readSession("step-1", "rec-1")).toEqual([]);
    // Nor while the person's id is not known.
    expect((await as(null).scan("step-1")).saved).toEqual([]);
    expect(db.parts.size).toBe(1);

    // The person who recorded it signs in again and gets it back.
    expect((await as("user-a").scan("step-1")).saved).toHaveLength(1);
    expect(await as("user-a").readSession("step-1", "rec-1")).toHaveLength(1);
  });

  it("rebuilds only the person's own journals, and leaves another person's alone", async () => {
    const { keeper, as, db } = setup();
    const journal = keeper.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(0));
    journal.append(part(0), new Blob(["a"], { type: "audio/webm" }), 1_000);
    journal.leave(part(0));
    await settle();
    expect([...db.journals.values()][0]).toMatchObject({ userId: "user-a" });

    expect(await as("user-b").scan("step-1")).toEqual({ saved: [], incomplete: false });
    expect(db.journals.size).toBe(1);
    expect(db.parts.size).toBe(0);

    expect((await as("user-a").scan("step-1")).saved).toHaveLength(1);
    expect([...db.parts.values()][0]).toMatchObject({ userId: "user-a", interrupted: true });
  });

  it("offers no recording kept before it carried who recorded it, and lets it age out", async () => {
    const { keeper, db, later } = setup();
    await db.putPart({
      flowId: "flow-1",
      stepId: "step-1",
      sessionId: "rec-old",
      index: 0,
      blob: new Blob(["audio"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      interrupted: false,
      contract: CONTRACT,
      streamed: false
    });
    expect((await keeper.scan("step-1")).saved).toEqual([]);
    expect(await keeper.readSession("step-1", "rec-old")).toEqual([]);
    expect(db.parts.size).toBe(1);
    later(RECORDING_TTL_MS + 2_000);
    await keeper.scan("step-1");
    expect(db.parts.size).toBe(0);
  });

  it("deletes anyone's recording with no activity for a day", async () => {
    const { keeper, as, db, later } = setup();
    await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["audio"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    later(RECORDING_TTL_MS + 2_000);
    await as("user-b").scan("step-1");
    expect(db.parts.size).toBe(0);
  });

  it("never replaces a part it said is kept when two tabs continue the same recording", async () => {
    const { keeper, as, db } = setup();
    const keep = (tab: RecordingKeeper, index: number, audio: string) =>
      tab.keepPart("step-1", {
        sessionId: "rec-1",
        index,
        blob: new Blob([audio], { type: "audio/webm" }),
        mimeType: "audio/webm",
        durationMs: 1_000,
        capturedAt: START + index * 60_000,
        contract: CONTRACT,
        streamed: false
      });
    await keep(keeper, 0, "audio");
    // "Spara och fortsätt senare": the form that recorded it lets go.
    await keeper.close();

    // Two tabs of the same person press Fortsätt on the kept recording at once.
    const first = as("user-a");
    const second = as("user-a");
    const [won, lost] = await Promise.all([
      first.resume("step-1", "rec-1", CONTRACT),
      second.resume("step-1", "rec-1", CONTRACT)
    ]);
    expect(won).toMatchObject({ kind: "continued", parts: [{ index: 0 }] });
    // The second is refused as it takes over: it gets no parts to add or upload.
    expect(lost).toEqual({ kind: "refused", refusal: "open_elsewhere" });

    const firstKept = await keep(first, 1, "AAAA");
    expect(firstKept).toBe("device");
    // A part the second tab records of it anyway stays in that tab.
    expect(await keep(second, 1, "BBBB")).toBe("tab");
    const stored = await first.readSession("step-1", "rec-1");
    expect(await Promise.all(stored.map((kept) => kept.blob.text()))).toEqual(["audio", "AAAA"]);
    expect(db.parts.size).toBe(2);
  });

  it("refuses Fortsätt in a tab while the tab that records the recording holds it", async () => {
    const { keeper, as, db } = setup();
    const journal = keeper.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(0));
    journal.append(part(0), new Blob(["AAAA"], { type: "audio/webm" }), 1_000);
    await settle();
    await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["AAAA"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    // The recording goes on: its next part records now.
    journal.begin(part(1));
    journal.append(part(1), new Blob(["CCCC"], { type: "audio/webm" }), 1_000);
    await settle();
    const before = JSON.stringify([...db.parts.keys(), ...db.journals.keys(), ...db.chunks.keys()]);

    const other = as("user-a");
    expect(await other.resume("step-1", "rec-1", CONTRACT)).toEqual({
      kind: "refused",
      refusal: "open_elsewhere"
    });
    expect(await other.discard("step-1", "rec-1")).toBe("open_elsewhere");
    await other.forgetAll();
    expect(JSON.stringify([...db.parts.keys(), ...db.journals.keys(), ...db.chunks.keys()])).toBe(
      before
    );
  });

  describe("Fortsätt as one operation of the keeper", () => {
    const HOLD = "eneo-flow-recording-holder:flow-1::step-1::rec-1";
    async function kept(db: ReturnType<typeof memoryRecordings>) {
      await db.putPart({
        flowId: "flow-1",
        stepId: "step-1",
        sessionId: "rec-1",
        index: 0,
        blob: new Blob(["audio"], { type: "audio/webm" }),
        mimeType: "audio/webm",
        durationMs: 1_000,
        capturedAt: START,
        interrupted: false,
        contract: CONTRACT,
        streamed: false,
        userId: "user-a"
      });
    }

    it("continues once when pressed twice, and never refuses its own hold", async () => {
      const { keeper, db, lockManager } = setup();
      await kept(db);
      const [one, two] = await Promise.all([
        keeper.resume("step-1", "rec-1", CONTRACT),
        keeper.resume("step-1", "rec-1", CONTRACT)
      ]);
      expect([one.kind, two.kind]).toEqual(["continued", "busy"]);
      expect(lockManager.isHeld(HOLD)).toBe(true);
      expect(keeper.keeping("step-1", "rec-1", 0)).toBe("device");
      // Asked again while it holds the recording, it answers from its own book.
      expect(await keeper.resume("step-1", "rec-1", CONTRACT)).toMatchObject({
        kind: "continued"
      });
      expect(await keeper.discard("step-1", "rec-1")).toBe("discarded");
    });

    it("lets go of a hold that led to no takeover", async () => {
      const { keeper, db, lockManager } = setup();
      // Nothing kept: nothing to continue.
      expect(await keeper.resume("step-1", "rec-1", CONTRACT)).toEqual({ kind: "empty" });
      expect(lockManager.isHeld(HOLD)).toBe(false);

      await kept(db);
      expect(
        await keeper.resume("step-1", "rec-1", { ...CONTRACT, inputFormat: "document" })
      ).toEqual({ kind: "refused", refusal: "step_changed" });
      expect(lockManager.isHeld(HOLD)).toBe(false);

      vi.spyOn(db, "listParts").mockRejectedValueOnce(new Error("blocked"));
      expect(await keeper.resume("step-1", "rec-1", CONTRACT)).toEqual({
        kind: "refused",
        refusal: "read_failed"
      });
      expect(lockManager.isHeld(HOLD)).toBe(false);
      // None of it is this form's: forgetting all removes nothing.
      await keeper.forgetAll();
      expect(db.parts.size).toBe(1);
    });

    it("refuses with the read error, not as open elsewhere, when asking to hold throws", async () => {
      const { keeper, db, lockManager } = setup();
      await kept(db);
      lockManager.failRequests("eneo-flow-recording-holder:");
      expect(await keeper.resume("step-1", "rec-1", CONTRACT)).toEqual({
        kind: "refused",
        refusal: "read_failed"
      });
      expect(await keeper.discard("step-1", "rec-1")).toBe("read_failed");
      expect(db.parts.size).toBe(1);
      lockManager.failRequests(null);
      expect(await keeper.resume("step-1", "rec-1", CONTRACT)).toMatchObject({
        kind: "continued"
      });
    });

    it("takes nothing over when the form closes while it waits for the hold or reads", async () => {
      const { keeper, as, db, lockManager } = setup();
      await kept(db);
      const grant = lockManager.deferGrants();
      const waiting = keeper.resume("step-1", "rec-1", CONTRACT);
      const closed = keeper.close();
      grant();
      expect(await waiting).toEqual({ kind: "closed" });
      await closed;
      expect(lockManager.isHeld(HOLD)).toBe(false);
      expect(keeper.keeping("step-1", "rec-1", 0)).toBeUndefined();

      const reading = as("user-a");
      let answer = () => {};
      const listParts = db.listParts.bind(db);
      vi.spyOn(db, "listParts").mockImplementationOnce(async (...args) => {
        const parts = await listParts(...args);
        await new Promise<void>((resolve) => {
          answer = resolve;
        });
        return parts;
      });
      const read = reading.resume("step-1", "rec-1", CONTRACT);
      await settle();
      const gone = reading.close();
      answer();
      expect(await read).toEqual({ kind: "closed" });
      await gone;
      expect(lockManager.isHeld(HOLD)).toBe(false);
      expect(reading.keeping("step-1", "rec-1", 0)).toBeUndefined();
      expect(db.parts.size).toBe(1);
    });

    it("lets another form continue once the holder let go, and the one that let go removes nothing", async () => {
      const { keeper, as, db } = setup();
      await kept(db);
      expect((await keeper.resume("step-1", "rec-1", CONTRACT)).kind).toBe("continued");
      await keeper.close();

      const other = as("user-a");
      expect((await other.resume("step-1", "rec-1", CONTRACT)).kind).toBe("continued");
      await keeper.forgetAll();
      expect(db.parts.size).toBe(1);
    });
  });

  describe("a tab closes mid-part and another continues the recording", () => {
    /**
     * Tab A keeps parts 0 and 1 and journals part 2 ("AAAA"), then closes: the browser lets
     * go of its lock, nothing commits or leaves. A's own lock manager stands for its tab;
     * in the shared one its part's lock is held elsewhere until the tab closes.
     */
    async function tabClosesMidPart() {
      const { db, lockManager, as } = setup();
      const tabA = new RecordingKeeper("flow-1", "user-a", db, fakeLocks().locks, () => START);
      for (const index of [0, 1]) {
        await tabA.keepPart("step-1", {
          sessionId: "rec-1",
          index,
          blob: new Blob([`part${index}`], { type: "audio/webm" }),
          mimeType: "audio/webm",
          durationMs: 1_000,
          capturedAt: START + index * 60_000,
          contract: CONTRACT,
          streamed: false
        });
      }
      const journalA = tabA.journalFor(
        "step-1",
        () => CONTRACT,
        () => false
      );
      journalA.begin(part(2));
      journalA.append(part(2), new Blob(["AAAA"], { type: "audio/webm" }), 1_000);
      await settle();
      const lockA = "eneo-flow-recording:flow-1::step-1::rec-1::0002";
      lockManager.holdElsewhere(lockA);
      return { db, as, closeA: () => lockManager.releaseElsewhere(lockA) };
    }

    /** Fortsätt as the form does it, then the next part recorded ("BBBB") and finished. */
    async function continueAndRecord(tab: RecordingKeeper): Promise<number> {
      const outcome = await tab.resume("step-1", "rec-1", CONTRACT);
      if (outcome.kind !== "continued") throw new Error(`not continued: ${outcome.kind}`);
      const index = outcome.parts.reduce((next, kept) => Math.max(next, kept.index + 1), 0);
      const journal = tab.journalFor(
        "step-1",
        () => CONTRACT,
        () => false
      );
      journal.begin(part(index));
      journal.append(part(index), new Blob(["BBBB"], { type: "audio/webm" }), 1_000);
      await settle();
      await tab.keepPart("step-1", {
        sessionId: "rec-1",
        index,
        blob: new Blob(["BBBB"], { type: "audio/webm" }),
        mimeType: "audio/webm",
        durationMs: 1_000,
        capturedAt: START + index * 60_000,
        contract: CONTRACT,
        streamed: false
      });
      return index;
    }

    /** Every part and journal chunk on the device, by its key, as text. */
    async function onDevice(db: ReturnType<typeof memoryRecordings>) {
      const entries = [
        ...[...db.parts].map(([key, kept]) => [`part ${key}`, kept.blob] as const),
        ...[...db.chunks].map(([key, chunk]) => [`chunk ${key}`, chunk.blob] as const)
      ];
      return Object.fromEntries(
        await Promise.all(entries.map(async ([key, blob]) => [key, await blob.text()]))
      ) as Record<string, string>;
    }

    it("keeps the closed tab's audio when the other tab scans again before it continues", async () => {
      const { db, as, closeA } = await tabClosesMidPart();
      const tabB = as("user-a");
      closeA();
      // The form opened anew in B: its scan rebuilds what A left.
      expect((await tabB.scan("step-1")).saved).toMatchObject([{ sessionId: "rec-1", parts: 3 }]);

      expect(await continueAndRecord(tabB)).toBe(3);
      await as("user-a").scan("step-1");
      const stored = await onDevice(db);
      expect(Object.values(stored), JSON.stringify(stored)).toContain("AAAA");
    });
  });

  describe("what a scan leaves of a journal whose lock is free", () => {
    const JOURNAL: JournalMeta = {
      flowId: "flow-1",
      stepId: "step-1",
      sessionId: "rec-1",
      index: 2,
      mimeType: "audio/webm;codecs=opus",
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
      const { db, keeper } = setup({ locks });
      for (const index of [0, 1]) {
        await keeper.keepPart("step-1", {
          sessionId: "rec-1",
          index,
          blob: new Blob([`part${index}`], { type: "audio/webm" }),
          mimeType: "audio/webm",
          durationMs: 1_000,
          capturedAt: START + index * 60_000,
          contract: CONTRACT,
          streamed: false
        });
      }
      await db.putJournal({ ...JOURNAL, lastChunkAt });
      for (const [seq, audio] of Object.entries(chunks)) {
        await db.appendChunk(JOURNAL, Number(seq), {
          blob: new Blob([audio], { type: "audio/webm" }),
          recordedMs: (Number(seq) + 1) * 1_000,
          at: lastChunkAt
        });
      }
      return { db, keeper };
    }

    const part2 = (db: ReturnType<typeof memoryRecordings>) =>
      db.parts.get("flow-1::step-1::rec-1::0002");

    it("rebuilds readable chunks into part 2 and drops the journal", async () => {
      const { db, keeper } = await keptWithJournal({ 0: "ab", 1: "cd" });
      expect(await keeper.scan("step-1")).toMatchObject({
        incomplete: false,
        saved: [{ sessionId: "rec-1", parts: 3 }]
      });
      expect(db.journals.size).toBe(0);
      expect(db.chunks.size).toBe(0);
      expect(part2(db)).toMatchObject({ index: 2, interrupted: true });
      expect(await part2(db)!.blob.text()).toBe("abcd");
    });

    it("drops a journal with no chunks and makes no part of it", async () => {
      const { db, keeper } = await keptWithJournal({});
      expect(await keeper.scan("step-1")).toMatchObject({
        incomplete: false,
        saved: [{ sessionId: "rec-1", parts: 2 }]
      });
      expect(db.journals.size).toBe(0);
      expect(part2(db)).toBeUndefined();
    });

    it("rebuilds only the chunks before a gap, and drops the journal with the chunks after it", async () => {
      const { db, keeper } = await keptWithJournal({ 0: "ab", 2: "ef" });
      expect(await keeper.scan("step-1")).toMatchObject({
        incomplete: false,
        saved: [{ sessionId: "rec-1", parts: 3 }]
      });
      expect(db.journals.size).toBe(0);
      expect(db.chunks.size).toBe(0);
      expect(await part2(db)!.blob.text()).toBe("ab");
    });

    it("leaves the journal and its chunks when reading them throws, scan after scan", async () => {
      const { db, keeper } = await keptWithJournal({ 0: "ab" });
      vi.spyOn(db, "readChunks").mockRejectedValue(new Error("blocked"));
      for (let scan = 0; scan < 2; scan += 1) {
        expect(await keeper.scan("step-1")).toMatchObject({
          incomplete: true,
          saved: [{ sessionId: "rec-1", parts: 2 }]
        });
        expect(db.journals.size).toBe(1);
        expect(db.chunks.size).toBe(1);
        expect(part2(db)).toBeUndefined();
      }
    });

    it("leaves the journal and its chunks when they are not read in time, scan after scan", async () => {
      const { db, keeper } = await keptWithJournal({ 0: "ab" });
      vi.spyOn(db, "readChunks").mockResolvedValue(null);
      for (let scan = 0; scan < 2; scan += 1) {
        expect(await keeper.scan("step-1")).toMatchObject({
          incomplete: true,
          saved: [{ sessionId: "rec-1", parts: 2 }]
        });
        expect(db.journals.size).toBe(1);
        expect(db.chunks.size).toBe(1);
        expect(part2(db)).toBeUndefined();
      }
    });

    it("drops an expired journal and its chunks without making a part of it", async () => {
      const { db, keeper } = await keptWithJournal(
        { 0: "ab" },
        { lastChunkAt: START - RECORDING_TTL_MS - 1_000 }
      );
      expect(await keeper.scan("step-1")).toMatchObject({
        incomplete: false,
        saved: [{ sessionId: "rec-1", parts: 2 }]
      });
      expect(db.journals.size).toBe(0);
      expect(db.chunks.size).toBe(0);
      expect(part2(db)).toBeUndefined();
    });

    it("leaves the journal and its chunks without Web Locks, scan after scan", async () => {
      const { db, keeper } = await keptWithJournal({ 0: "ab" }, { locks: false });
      for (let scan = 0; scan < 2; scan += 1) {
        expect(await keeper.scan("step-1")).toEqual({
          incomplete: false,
          saved: [expect.objectContaining({ sessionId: "rec-1", parts: 2 })]
        });
        expect(db.journals.size).toBe(1);
        expect(db.chunks.size).toBe(1);
        expect(part2(db)).toBeUndefined();
      }
    });
  });

  describe("one keeper at a time holds a recording", () => {
    const HOLD = "eneo-flow-recording-holder:flow-1::step-1::rec-1";
    const finished = (index: number, audio = "audio") => ({
      sessionId: "rec-1",
      index,
      blob: new Blob([audio], { type: "audio/webm" }),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START + index * 60_000,
      contract: CONTRACT,
      streamed: false
    });
    /** A promise the test settles. */
    function deferred<T = void>() {
      let resolve!: (value: T) => void;
      let reject!: (error: unknown) => void;
      const promise = new Promise<T>((yes, no) => {
        resolve = yes;
        reject = no;
      });
      return { promise, resolve, reject };
    }
    /** Every key on the device: parts, journals and chunks. */
    const keys = (db: ReturnType<typeof memoryRecordings>) => [
      ...db.parts.keys(),
      ...[...db.journals.keys()].map((key) => `journal ${key}`),
      ...[...db.chunks.keys()].map((key) => `chunk ${key}`)
    ];

    it("takes the hold as a recording's first part begins, and keeps it between parts", async () => {
      const { keeper, lockManager } = setup();
      const journal = keeper.journalFor(
        "step-1",
        () => CONTRACT,
        () => false
      );
      journal.begin(part(0));
      await settle();
      expect(lockManager.isHeld(HOLD)).toBe(true);
      expect(await keeper.keepPart("step-1", finished(0))).toBe("device");
      expect(lockManager.isHeld(HOLD)).toBe(true);
    });

    it("writes nothing of a recording another keeper holds: its parts stay in the tab", async () => {
      const { keeper, as, db } = setup();
      await keeper.keepPart("step-1", finished(0, "AAAA"));
      const before = keys(db);

      const other = as("user-a");
      const journal = other.journalFor(
        "step-1",
        () => CONTRACT,
        () => false
      );
      journal.begin(part(1));
      journal.append(part(1), new Blob(["BBBB"], { type: "audio/webm" }), 1_000);
      await settle();
      expect(await other.keepPart("step-1", finished(1, "BBBB"))).toBe("tab");
      expect(other.keeping("step-1", "rec-1", 1)).toBe("tab");
      expect(other.degradation("step-1")).toBe("failed");
      // Nor does it remove anything: the holder's recording is as it was.
      await other.forgetPart("step-1", "rec-1", 0);
      expect(await other.forgetSession("step-1", "rec-1")).toBe(true);
      await other.forgetAll();
      expect(keys(db)).toEqual(before);
    });

    it("writes nothing when the lock request throws, and tries again as the next part begins", async () => {
      const { keeper, db, lockManager } = setup();
      lockManager.failRequests("eneo-flow-recording-holder:");
      const journal = keeper.journalFor(
        "step-1",
        () => CONTRACT,
        () => false
      );
      journal.begin(part(0));
      journal.append(part(0), new Blob(["a"], { type: "audio/webm" }), 1_000);
      await settle();
      expect(await keeper.keepPart("step-1", finished(0))).toBe("tab");
      expect(keeper.degradation("step-1")).toBe("failed");
      expect(keys(db)).toEqual([]);

      // One failed request does not leave the rest of a long recording without a copy.
      lockManager.failRequests(null);
      journal.begin(part(1));
      await settle();
      expect(await keeper.keepPart("step-1", finished(1))).toBe("device");
      expect(keys(db)).toEqual(["flow-1::step-1::rec-1::0001"]);
    });

    it("throws away nothing on the device of a recording it never held", async () => {
      const { keeper, db, lockManager } = setup();
      lockManager.failRequests("eneo-flow-recording-holder:");
      expect(await keeper.keepPart("step-1", finished(0))).toBe("tab");
      await db.putPart({
        ...finished(0, "elsewhere"),
        flowId: "flow-1",
        stepId: "step-1",
        interrupted: false,
        userId: "user-a"
      });
      expect(await keeper.forgetSession("step-1", "rec-1")).toBe(true);
      expect(db.parts.size).toBe(1);
    });

    it("lets go only after a write that is under way has ended", async () => {
      const { keeper, db, lockManager } = setup();
      const put = deferred();
      const putPart = db.putPart.bind(db);
      vi.spyOn(db, "putPart").mockImplementationOnce(async (stored) => {
        await put.promise;
        await putPart(stored);
      });
      const kept = keeper.keepPart("step-1", finished(0));
      await settle();
      const closed = keeper.close();
      await settle();
      expect(lockManager.isHeld(HOLD)).toBe(true);
      put.resolve();
      expect(await kept).toBe("device");
      await closed;
      expect(lockManager.isHeld(HOLD)).toBe(false);
      expect(db.parts.size).toBe(1);
    });

    it("writes nothing once it has let go, and lets go of a hold granted late", async () => {
      const { keeper, db, lockManager } = setup();
      const grant = lockManager.deferGrants();
      keeper
        .journalFor(
          "step-1",
          () => CONTRACT,
          () => false
        )
        .begin(part(0));
      const closed = keeper.close();
      grant();
      await closed;
      await settle();
      expect(lockManager.isHeld(HOLD)).toBe(false);
      expect(await keeper.keepPart("step-1", finished(0))).toBe("tab");
      expect(keys(db)).toEqual([]);
    });

    it("lets go after a removal that failed, and keeps no right to remove later", async () => {
      const { keeper, as, db, lockManager } = setup();
      await keeper.keepPart("step-1", finished(0, "AAAA"));
      vi.spyOn(db, "deleteSession").mockRejectedValueOnce(new Error("blocked"));
      expect(await keeper.forgetSession("step-1", "rec-1")).toBe(false);
      expect(lockManager.isHeld(HOLD)).toBe(false);

      // Another keeper now holds the recording and adds to it.
      const other = as("user-a");
      expect(await other.keepPart("step-1", finished(1, "BBBB"))).toBe("device");
      await keeper.forgetAll();
      expect(db.parts.size).toBe(2);
    });

    it("lets go when the form closes, and the next keeper can hold the recording", async () => {
      const { keeper, as, db, lockManager } = setup();
      await keeper.keepPart("step-1", finished(0, "AAAA"));
      await keeper.close();
      expect(lockManager.isHeld(HOLD)).toBe(false);

      const other = as("user-a");
      expect(await other.keepPart("step-1", finished(1, "BBBB"))).toBe("device");
      // The keeper that let go has no right left to remove what the other holds.
      await keeper.forgetAll();
      await keeper.forgetPart("step-1", "rec-1", 1);
      expect(db.parts.size).toBe(2);
    });

    it("waits for a removal started as the form closes before it lets go", async () => {
      const { keeper, db, lockManager } = setup();
      await keeper.keepPart("step-1", finished(0));
      const removal = deferred();
      const deleteSession = db.deleteSession.bind(db);
      vi.spyOn(db, "deleteSession").mockImplementationOnce(async (...args) => {
        await removal.promise;
        await deleteSession(...args);
      });
      void keeper.forgetAll();
      const closed = keeper.close();
      await settle();
      expect(lockManager.isHeld(HOLD)).toBe(true);
      removal.resolve();
      await closed;
      expect(lockManager.isHeld(HOLD)).toBe(false);
      expect(db.parts.size).toBe(0);
    });

    it("opens again after it was closed, as the app's strict mode mounts the form twice", async () => {
      const { keeper, lockManager } = setup();
      const close = keeper.open();
      close();
      keeper.open();
      expect(await keeper.keepPart("step-1", finished(0))).toBe("device");
      expect(lockManager.isHeld(HOLD)).toBe(true);
    });

    it("holds nothing without Web Locks, and keeps parts as before", async () => {
      const { keeper, as, db } = setup({ locks: false });
      expect(await keeper.keepPart("step-1", finished(0, "AAAA"))).toBe("device");
      expect(await as("user-a").keepPart("step-1", finished(1, "BBBB"))).toBe("device");
      expect(db.parts.size).toBe(2);
    });
  });

  it("says when kept recordings could not be read", async () => {
    const { keeper, db } = setup();
    vi.spyOn(db, "listParts").mockRejectedValue(new Error("blocked"));
    expect(await keeper.scan("step-1")).toEqual({ saved: [], incomplete: true });
  });

  it("works without storage: nothing is kept and nothing is offered", async () => {
    const keeper = new RecordingKeeper("flow-1", "user-a", null, null);
    expect(keeper.available).toBe(false);
    expect(await keeper.scan("step-1")).toEqual({ saved: [], incomplete: false });
    keeper
      .journalFor(
        "step-1",
        () => CONTRACT,
        () => false
      )
      .begin(part(0));
    expect(keeper.degradation("step-1")).toBe("failed");
  });
});

describe("resumeRefusal", () => {
  const parts = [{ mimeType: "audio/webm;codecs=opus" }, { mimeType: "audio/webm" }];

  it("lets a kept recording continue on a step that still takes it", () => {
    expect(resumeRefusal({ ...CONTRACT, publishedFlowVersion: 9 }, parts)).toBeNull();
    expect(resumeRefusal({ ...CONTRACT, acceptedMimetypes: ["audio/*"] }, parts)).toBeNull();
  });

  it("refuses where the step no longer takes it as it is", () => {
    expect(resumeRefusal({ ...CONTRACT, inputFormat: "document" }, parts)).toBe("step_changed");
    expect(resumeRefusal(contractSnapshot(null, 4), parts)).toBe("step_changed");
    expect(resumeRefusal({ ...CONTRACT, maxFiles: 1 }, parts)).toBe("too_many_parts");
    expect(resumeRefusal({ ...CONTRACT, acceptedMimetypes: ["audio/mp4"] }, parts)).toBe(
      "type_not_accepted"
    );
  });
});
