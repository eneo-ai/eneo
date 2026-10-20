import { describe, expect, it } from "vitest";
import { combineSyncProgress, finishedSyncs, type IntegrationSyncProgress } from "./sync-progress";

function entry(fields: Partial<IntegrationSyncProgress>): IntegrationSyncProgress {
  return {
    integration_knowledge_id: "a",
    sync_type: "full",
    phase: "processing",
    started_at: "2026-10-14T10:00:00Z",
    updated_at: "2026-10-14T10:01:00Z",
    total: 10,
    done: 4,
    indexed: 3,
    unchanged: 0,
    skipped: 1,
    deleted: 0,
    ...fields
  };
}

describe("combineSyncProgress", () => {
  it("is null when nothing syncs", () => {
    expect(combineSyncProgress([])).toBeNull();
  });

  it("adds the counts, starts at the earliest item and reports the slowest phase", () => {
    expect(
      combineSyncProgress([
        entry({ phase: "finishing", started_at: "2026-10-14T10:05:00Z" }),
        entry({ phase: "discovering", total: 20, done: 6, indexed: 6, skipped: 0 })
      ])
    ).toEqual({
      phase: "discovering",
      startedAt: "2026-10-14T10:00:00Z",
      total: 30,
      done: 10,
      indexed: 9,
      unchanged: 0,
      skipped: 1,
      syncing: 2,
      background: false
    });
  });

  it("marks a sync of change notifications' delta passes only as background", () => {
    expect(combineSyncProgress([entry({ sync_type: "delta" })])?.background).toBe(true);
    expect(
      combineSyncProgress([entry({ sync_type: "delta" }), entry({ sync_type: "full" })])?.background
    ).toBe(false);
  });

  it("does not know the total while one item does not", () => {
    expect(combineSyncProgress([entry({}), entry({ total: null })])?.total).toBeNull();
  });
});

describe("finishedSyncs", () => {
  it("lists the syncs that were running and are gone", () => {
    const running = { a: entry({}), b: entry({ integration_knowledge_id: "b" }) };
    expect(finishedSyncs(running, { b: running.b })).toEqual(["a"]);
    expect(finishedSyncs({}, running)).toEqual([]);
  });
});
