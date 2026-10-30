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
  const keeper = new RecordingKeeper("flow-1", db, locks ? lockManager.locks : null, () => now);
  return {
    db,
    keeper,
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
      contract: CONTRACT
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
    const journal = keeper.journalFor("step-1", () => CONTRACT);
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

  it("drops the journal of a part that was stored", async () => {
    const { keeper, db } = setup();
    const journal = keeper.journalFor("step-1", () => CONTRACT);
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
      contract: CONTRACT
    });
    expect(db.journals.size).toBe(0);
    expect(db.chunks.size).toBe(0);
  });

  it("leaves alone a part another tab still records", async () => {
    const { keeper, db, lockManager } = setup();
    const journal = keeper.journalFor("step-1", () => CONTRACT);
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
    withoutLocks.keeper.journalFor("step-1", () => CONTRACT).begin(part(0));
    expect(withoutLocks.keeper.degradation("step-1")).toBe("unavailable");

    const mp4 = setup();
    mp4.keeper.journalFor("step-1", () => CONTRACT).begin({ ...part(0), mimeType: "audio/mp4" });
    expect(mp4.keeper.degradation("step-1")).toBe("unavailable");
    expect(mp4.db.journals.size).toBe(0);
  });

  it("says when storage falls behind, and keeps what it wrote", async () => {
    const { keeper, db } = setup();
    const appendChunk = vi.spyOn(db, "appendChunk").mockReturnValue(new Promise(() => undefined));
    const journal = keeper.journalFor("step-1", () => CONTRACT);
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
      contract: CONTRACT
    });
    expect(kept).toBe("tab");
    expect(keeper.keeping("step-1", "rec-1", 0)).toBe("tab");
  });

  it("forgets a recording thrown away: its parts, its journal and parts handed over late", async () => {
    const { keeper, db } = setup();
    const journal = keeper.journalFor("step-1", () => CONTRACT);
    await keeper.keepPart("step-1", {
      sessionId: "rec-1",
      index: 0,
      blob: new Blob(["audio"]),
      mimeType: "audio/webm",
      durationMs: 1_000,
      capturedAt: START,
      contract: CONTRACT
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
      contract: CONTRACT
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
      contract: CONTRACT
    });
    later(RECORDING_TTL_MS + 2_000);
    expect((await keeper.scan("step-1")).saved).toEqual([]);
    expect(db.parts.size).toBe(0);
  });

  it("says when kept recordings could not be read", async () => {
    const { keeper, db } = setup();
    vi.spyOn(db, "listParts").mockRejectedValue(new Error("blocked"));
    expect(await keeper.scan("step-1")).toEqual({ saved: [], incomplete: true });
  });

  it("works without storage: nothing is kept and nothing is offered", async () => {
    const keeper = new RecordingKeeper("flow-1", null, null);
    expect(keeper.available).toBe(false);
    expect(await keeper.scan("step-1")).toEqual({ saved: [], incomplete: false });
    keeper.journalFor("step-1", () => CONTRACT).begin(part(0));
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
