import { describe, expect, it, vi } from "vitest";
import { JOURNAL_MAX_PENDING_CHUNKS } from "./recording-journal";
import {
  contractSnapshot,
  RecordingKeeper,
  resumeRefusal,
  storedPartFile,
  type JournalPart
} from "./recording-keeper";
import { memoryRecordings, RECORDING_TTL_MS, type ContractSnapshot } from "./recording-store";
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

  it("keeps a finished part's full audio when another tab scans while it is still being written", async () => {
    const { db, as } = setup();
    const tabA = as("user-a");
    const journal = tabA.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(0));
    journal.append(part(0), new Blob(["AA"], { type: "audio/webm" }), 500);
    await settle();
    // The full write of the finished part waits until the other tab has scanned.
    let write = () => {};
    const written = new Promise<void>((resolve) => {
      write = resolve;
    });
    const putPart = db.putPart.bind(db);
    vi.spyOn(db, "putPart").mockImplementation(async (stored) => {
      if (!stored.interrupted) await written;
      return putPart(stored);
    });
    const kept = tabA.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["AAAA-full"], { type: "audio/webm" }),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT,
      streamed: false
    });
    await settle();
    // The form goes while the part is still being written: its hold goes, the part's journal stays.
    await tabA.close();
    await as("user-a").scan("step-1");
    write();
    expect(await kept).toBe("device");
    await as("user-a").scan("step-1");
    const stored = await as("user-a").readSession("step-1", "rec-1");
    expect(await Promise.all(stored.map((kept) => kept.blob.text()))).toEqual(["AAAA-full"]);
    expect(db.journals.size).toBe(0);
  });

  describe("one form at a time continues a kept recording", () => {
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
    /** Every key on the device: parts, journals and chunks. */
    const keys = (db: ReturnType<typeof memoryRecordings>) =>
      JSON.stringify([...db.parts.keys(), ...db.journals.keys(), ...db.chunks.keys()]);
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

    it("never replaces a part it said is kept when two tabs continue the same recording", async () => {
      const { keeper, as } = setup();
      await keeper.keepPart("step-1", finished(0));
      // "Spara och fortsätt senare": the form that recorded it goes.
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
      expect(second.keeping("step-1", "rec-1", 0)).toBeUndefined();

      expect(await first.keepPart("step-1", finished(1, "AAAA"))).toBe("device");
      const stored = await first.readSession("step-1", "rec-1");
      expect(await Promise.all(stored.map((part) => part.blob.text()))).toEqual(["audio", "AAAA"]);
    });

    it("refuses Fortsätt and Kassera in another tab while a tab records the recording", async () => {
      const { keeper, as, db, lockManager } = setup();
      const journal = keeper.journalFor(
        "step-1",
        () => CONTRACT,
        () => false
      );
      journal.begin(part(0));
      journal.append(part(0), new Blob(["AAAA"], { type: "audio/webm" }), 1_000);
      await settle();
      // The hold is taken as the first part begins, and stays between parts.
      expect(lockManager.isHeld(HOLD)).toBe(true);
      expect(await keeper.keepPart("step-1", finished(0, "AAAA"))).toBe("device");
      journal.begin(part(1));
      journal.append(part(1), new Blob(["CCCC"], { type: "audio/webm" }), 1_000);
      await settle();
      expect(lockManager.isHeld(HOLD)).toBe(true);
      const before = keys(db);

      const other = as("user-a");
      expect(await other.resume("step-1", "rec-1", CONTRACT)).toEqual({
        kind: "refused",
        refusal: "open_elsewhere"
      });
      expect(await other.discard("step-1", "rec-1")).toBe("open_elsewhere");
      expect(keys(db)).toBe(before);

      // A refusal is not kept: once the recording tab's form goes, the other continues.
      await keeper.close();
      expect((await other.resume("step-1", "rec-1", CONTRACT)).kind).toBe("continued");
    });

    it("keeps parts as before while another tab holds the recording: the hold never stops a write", async () => {
      const { keeper, as, db } = setup();
      await kept(db);
      expect((await keeper.resume("step-1", "rec-1", CONTRACT)).kind).toBe("continued");
      expect(await as("user-a").keepPart("step-1", finished(1, "BBBB"))).toBe("device");
      expect(db.parts.size).toBe(2);
    });

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
      expect(db.parts.size).toBe(0);
      // A discarded recording is let go once it is gone.
      expect(lockManager.isHeld(HOLD)).toBe(false);
    });

    it("lets go of a hold that led to no takeover", async () => {
      const { keeper, db, lockManager } = setup();
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
      // Recording never depends on the hold.
      expect(await keeper.keepPart("step-1", finished(1))).toBe("device");
      expect(db.parts.size).toBe(2);
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
      await settle();
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

    it("lets go of a hold granted after the form went", async () => {
      const { keeper, lockManager } = setup();
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
      expect(lockManager.heldNames()).not.toContain(HOLD);
    });

    it("lets go when the form closes, and another form can then continue", async () => {
      const { keeper, as, db, lockManager } = setup();
      await kept(db);
      expect((await keeper.resume("step-1", "rec-1", CONTRACT)).kind).toBe("continued");
      await keeper.close();
      expect(lockManager.isHeld(HOLD)).toBe(false);
      expect((await as("user-a").resume("step-1", "rec-1", CONTRACT)).kind).toBe("continued");
    });

    it("opens again after it was closed, as the app's strict mode mounts the form twice", async () => {
      const { keeper, db, lockManager } = setup();
      await kept(db);
      const close = keeper.open();
      close();
      keeper.open();
      expect((await keeper.resume("step-1", "rec-1", CONTRACT)).kind).toBe("continued");
      expect(lockManager.isHeld(HOLD)).toBe(true);
    });

    it("holds nothing without Web Locks: another tab continues and discards as before", async () => {
      const { keeper, as, db } = setup({ locks: false });
      await kept(db);
      expect((await keeper.resume("step-1", "rec-1", CONTRACT)).kind).toBe("continued");
      expect((await as("user-a").resume("step-1", "rec-1", CONTRACT)).kind).toBe("continued");
      expect(await as("user-a").discard("step-1", "rec-1")).toBe("discarded");
      expect(db.parts.size).toBe(0);
    });
  });

  describe("Fortsätt numbers the next part over every number on the device", () => {
    /**
     * Tab A keeps parts 0 and 1 and journals part 2 ("AAAA"), then closes: the browser lets
     * go of its locks, nothing commits or leaves. A's own lock manager stands for its tab;
     * in the shared one its part's lock is held elsewhere until the tab closes.
     */
    async function tabClosesMidPart({ locks = true } = {}) {
      const { db, lockManager, as } = setup({ locks });
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
      return { db, as, lockManager, closeA: () => lockManager.releaseElsewhere(lockA) };
    }

    /** Fortsätt as the form does it, then the next part recorded ("BBBB") and finished. */
    async function continueAndRecord(tab: RecordingKeeper): Promise<number> {
      const outcome = await tab.resume("step-1", "rec-1", CONTRACT);
      if (outcome.kind !== "continued") throw new Error(`not continued: ${outcome.kind}`);
      const index = outcome.parts.reduce(
        (next, kept) => Math.max(next, kept.index + 1),
        tab.nextIndex("step-1", "rec-1")
      );
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

    /** The device's parts in order: their numbers, whether rebuilt, and their audio. */
    async function partsInOrder(db: ReturnType<typeof memoryRecordings>) {
      const parts = [...db.parts.values()].sort((a, b) => a.index - b.index);
      return Promise.all(
        parts.map(async (kept) => [kept.index, kept.interrupted, await kept.blob.text()])
      );
    }

    /** The journal chunks on the device, by key, as text. */
    async function chunks(db: ReturnType<typeof memoryRecordings>) {
      return Promise.all(
        [...db.chunks].map(async ([key, chunk]) => [key, await chunk.blob.text()] as const)
      );
    }

    it("keeps the closed tab's audio when the other tab continues from an earlier scan", async () => {
      const { db, as, closeA } = await tabClosesMidPart();
      const tabB = as("user-a");
      // B's form was open already: its scan ran while A still held the part's lock.
      expect((await tabB.scan("step-1")).saved).toMatchObject([{ sessionId: "rec-1", parts: 2 }]);
      closeA();
      const journalChunks = await chunks(db);

      // The next part takes the number over A's unfinished part, which is left as it is.
      expect(await continueAndRecord(tabB)).toBe(3);
      expect(await chunks(db)).toEqual(journalChunks);
      expect([...db.journals.values()].map((meta) => meta.index)).toEqual([2]);
      // Removed from the form, a part's row no longer counts; the number over the journal still does.
      await tabB.forgetPart("step-1", "rec-1", 3);
      expect(tabB.nextIndex("step-1", "rec-1")).toBe(3);

      // Its form goes; the next form that continues it numbers over the journal too.
      await tabB.close();
      expect(await continueAndRecord(as("user-a"))).toBe(3);
      // The journal is rebuilt as before, the next time a form opens.
      await as("user-a").scan("step-1");
      expect(await partsInOrder(db)).toEqual([
        [0, false, "part0"],
        [1, false, "part1"],
        [2, true, "AAAA"],
        [3, false, "BBBB"]
      ]);
      expect(db.journals.size).toBe(0);
    });

    it("keeps the closed tab's audio when the other tab scans again before it continues", async () => {
      const { db, as, closeA } = await tabClosesMidPart();
      const tabB = as("user-a");
      closeA();
      // The form opened anew in B: its scan rebuilds what A left.
      expect((await tabB.scan("step-1")).saved).toMatchObject([{ sessionId: "rec-1", parts: 3 }]);

      expect(await continueAndRecord(tabB)).toBe(3);
      await as("user-a").scan("step-1");
      expect(await partsInOrder(db)).toEqual([
        [0, false, "part0"],
        [1, false, "part1"],
        [2, true, "AAAA"],
        [3, false, "BBBB"]
      ]);
    });

    it("numbers over a journal also without Web Locks", async () => {
      const { db, as } = await tabClosesMidPart({ locks: false });
      const tabB = as("user-a");
      expect((await tabB.resume("step-1", "rec-1", CONTRACT)).kind).toBe("continued");
      expect(tabB.nextIndex("step-1", "rec-1")).toBe(3);
      expect(db.journals.size).toBe(1);
    });

    it("refuses with the read error when the recording's journals cannot be read, and holds nothing", async () => {
      const { db, as, closeA, lockManager } = await tabClosesMidPart();
      closeA();
      const tabB = as("user-a");
      vi.spyOn(db, "listJournals").mockRejectedValueOnce(new Error("blocked"));
      expect(await tabB.resume("step-1", "rec-1", CONTRACT)).toEqual({
        kind: "refused",
        refusal: "read_failed"
      });
      expect(lockManager.isHeld("eneo-flow-recording-holder:flow-1::step-1::rec-1")).toBe(false);
      expect(tabB.keeping("step-1", "rec-1", 0)).toBeUndefined();
      expect(tabB.nextIndex("step-1", "rec-1")).toBe(0);
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
