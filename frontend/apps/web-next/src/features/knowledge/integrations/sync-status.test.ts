import { describe, expect, it } from "vitest";
import type { IntegrationKnowledge } from "../knowledge";
import {
  compareSyncRevisions,
  latestTime,
  summarizeIntegrationSync,
  syncRevision
} from "./sync-status";

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function item(metadata: Partial<Metadata>): IntegrationKnowledge {
  return { name: "x", metadata: { size: 0, ...metadata } } as IntegrationKnowledge;
}

describe("summarizeIntegrationSync", () => {
  it.each([
    ["never", { last_sync_status: "never", document_count: 0 }, "never"],
    ["success with documents", { last_sync_status: "success", document_count: 3 }, "success"],
    ["success without documents", { last_sync_status: "success", document_count: 0 }, "empty"],
    ["error", { last_sync_status: "error", last_sync_error: "boom", document_count: 2 }, "error"],
    [
      "legacy row with a timestamp but no status",
      { last_synced_at: "2026-10-01T10:00:00Z", document_count: 4 },
      "success"
    ]
  ] as const)("maps %s", (_label, metadata, state) => {
    expect(summarizeIntegrationSync(item(metadata)).state).toBe(state);
  });

  it("keeps the error text and the last successful sync of a failed item", () => {
    const summary = summarizeIntegrationSync(
      item({
        last_sync_status: "error",
        last_sync_error: " Token expired ",
        last_synced_at: "2026-10-01T10:00:00Z",
        last_sync_attempted_at: "2026-10-02T10:00:00Z"
      })
    );
    expect(summary).toMatchObject({
      error: "Token expired",
      lastSyncedAt: "2026-10-01T10:00:00Z",
      lastSyncAttemptedAt: "2026-10-02T10:00:00Z"
    });
  });
});

describe("latestTime", () => {
  it.each([
    [null, null, null],
    ["2026-10-01T10:00:00Z", null, "2026-10-01T10:00:00Z"],
    [null, "2026-10-01T10:00:00Z", "2026-10-01T10:00:00Z"],
    ["2026-10-01T10:00:00Z", "2026-10-02T09:00:00+02:00", "2026-10-02T09:00:00+02:00"],
    ["2026-10-03T10:00:00Z", "2026-10-02T10:00:00Z", "2026-10-03T10:00:00Z"]
  ])("%s, %s → %s", (a, b, expected) => {
    expect(latestTime(a, b)).toBe(expected);
  });
});

describe("compareSyncRevisions", () => {
  const revision = (metadata: Partial<Metadata>) => syncRevision(item(metadata));
  const never = revision({});
  const synced = revision({
    last_sync_attempted_at: "2026-10-01T10:00:00Z",
    last_synced_at: "2026-10-01T10:05:00Z",
    document_count: 4
  });
  const failedLater = revision({
    last_sync_attempted_at: "2026-10-02T10:00:00+02:00",
    last_synced_at: "2026-10-01T10:05:00Z",
    document_count: 4
  });
  const legacy = revision({ last_synced_at: "2026-09-01T10:00:00Z", document_count: 4 });

  it("orders an item's revisions by its latest attempt, then its latest success", () => {
    expect([failedLater, never, synced, legacy].sort(compareSyncRevisions)).toEqual([
      never,
      legacy,
      synced,
      failedLater
    ]);
    expect(compareSyncRevisions(synced, synced)).toBe(0);
  });
});
