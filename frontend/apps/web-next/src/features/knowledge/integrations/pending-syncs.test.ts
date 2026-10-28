import { afterEach, describe, expect, it } from "vitest";
import {
  pendingSyncs,
  reportedSyncs,
  resetPendingSyncs,
  trackSyncs,
  untrackSyncs
} from "./pending-syncs";
import type { IntegrationSyncProgress } from "./sync-progress";

afterEach(resetPendingSyncs);

describe("pending syncs", () => {
  it("waits for an item's newest job only, and forgets a job on request", () => {
    trackSyncs([
      { jobId: "j1", knowledgeId: "a" },
      { jobId: "j2", knowledgeId: "b" }
    ]);
    // Started again before a worker took the first one.
    trackSyncs([{ jobId: "j3", knowledgeId: "a" }]);
    expect(pendingSyncs()).toEqual([
      { jobId: "j2", knowledgeId: "b" },
      { jobId: "j3", knowledgeId: "a" }
    ]);

    untrackSyncs(["j1", "j2"]);
    expect(pendingSyncs()).toEqual([{ jobId: "j3", knowledgeId: "a" }]);
  });

  it("finds the ones the worker reports on now", () => {
    const pending = [
      { jobId: "j1", knowledgeId: "a" },
      { jobId: "j2", knowledgeId: "b" }
    ];
    const running = { b: {} as IntegrationSyncProgress };
    expect(reportedSyncs(pending, running)).toEqual([{ jobId: "j2", knowledgeId: "b" }]);
  });

  it("does not take a change notification's delta pass for the full sync queued here", () => {
    const pending = [{ jobId: "j1", knowledgeId: "a" }];
    const delta = { a: { sync_type: "delta" } as IntegrationSyncProgress };
    expect(reportedSyncs(pending, delta)).toEqual([]);
    const full = { a: { sync_type: "full" } as IntegrationSyncProgress };
    expect(reportedSyncs(pending, full)).toEqual(pending);
  });
});
