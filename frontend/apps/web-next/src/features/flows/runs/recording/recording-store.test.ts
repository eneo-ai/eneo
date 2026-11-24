import { describe, expect, it, vi } from "vitest";
import {
  memoryRecordings,
  RECORDING_TTL_MS,
  sweepExpiredRecordings,
  type ContractSnapshot
} from "./recording-store";

const CONTRACT: ContractSnapshot = {
  publishedFlowVersion: 4,
  inputFormat: "audio",
  maxFiles: 4,
  maxFileSizeBytes: 10_000_000,
  acceptedMimetypes: ["audio/webm"]
};

const START = Date.UTC(2026, 9, 22, 8, 0, 0);

describe("sweepExpiredRecordings", () => {
  const stored = (flowId: string, stepId: string, sessionId: string, capturedAt: number) => ({
    flowId,
    stepId,
    sessionId,
    index: 0,
    blob: new Blob(["audio"]),
    mimeType: "audio/webm",
    durationMs: 1_000,
    capturedAt,
    interrupted: false,
    contract: CONTRACT,
    streamed: false
  });
  const journal = (flowId: string, sessionId: string, lastChunkAt: number, index = 0) => ({
    flowId,
    stepId: "step-1",
    sessionId,
    index,
    mimeType: "audio/webm",
    capturedAt: lastChunkAt,
    contract: CONTRACT,
    streamed: false,
    lastChunkAt,
    userId: "user-b"
  });

  it("deletes every recording on the device with no activity for a day, whoever made it", async () => {
    const db = memoryRecordings();
    const now = START + RECORDING_TTL_MS + 60_000;
    // Old, in other flows and steps than any form open now, and someone else's.
    await db.putPart({ ...stored("flow-1", "step-1", "old", START), userId: "user-a" });
    await db.putPart(stored("flow-2", "step-9", "older", START - 60_000));
    await db.putJournal(journal("flow-3", "left", START));
    await db.appendChunk(journal("flow-3", "left", START), 0, {
      blob: new Blob(["a"]),
      recordedMs: 1_000,
      at: START
    });
    // Recent.
    await db.putPart({ ...stored("flow-2", "step-1", "fresh", now - 60_000), userId: "user-a" });
    await db.putJournal(journal("flow-3", "recording", now - 1_000));
    // An old part whose recording goes on in a journal is not expired.
    await db.putPart({ ...stored("flow-4", "step-1", "going-on", START), userId: "user-b" });
    await db.putJournal(journal("flow-4", "going-on", now - 1_000, 1));

    await sweepExpiredRecordings(db, now);

    expect([...db.parts.values()].map((kept) => kept.sessionId).sort()).toEqual([
      "fresh",
      "going-on"
    ]);
    expect([...db.journals.values()].map((meta) => meta.sessionId).sort()).toEqual([
      "going-on",
      "recording"
    ]);
    expect(db.chunks.size).toBe(0);
  });

  it("does nothing without storage, or when storage cannot be read", async () => {
    await expect(sweepExpiredRecordings(null, START)).resolves.toBeUndefined();
    const db = memoryRecordings();
    vi.spyOn(db, "listAll").mockRejectedValue(new Error("blocked"));
    await expect(sweepExpiredRecordings(db, START)).resolves.toBeUndefined();
  });
});
