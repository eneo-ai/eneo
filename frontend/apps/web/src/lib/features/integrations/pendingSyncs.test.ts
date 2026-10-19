import { get } from "svelte/store";
import { beforeEach, describe, expect, it } from "vitest";
import {
  pendingSyncs,
  reportedSyncs,
  settledSyncs,
  trackSyncs,
  untrackSyncs
} from "./pendingSyncs";

describe("pendingSyncs", () => {
  beforeEach(() => pendingSyncs.set([]));

  it("waits for an item's newest job only", () => {
    trackSyncs([
      { jobId: "j1", knowledgeId: "a" },
      { jobId: "j2", knowledgeId: "b" }
    ]);
    trackSyncs([{ jobId: "j3", knowledgeId: "a" }]);

    expect(get(pendingSyncs)).toEqual([
      { jobId: "j2", knowledgeId: "b" },
      { jobId: "j3", knowledgeId: "a" }
    ]);

    untrackSyncs(["j2"]);
    expect(get(pendingSyncs)).toEqual([{ jobId: "j3", knowledgeId: "a" }]);
  });

  it("counts a job as settled once it is over, or gone after the list arrived", () => {
    const pending = [
      { jobId: "done", knowledgeId: "a" },
      { jobId: "running", knowledgeId: "b" },
      { jobId: "missing", knowledgeId: "c" }
    ];
    const jobs = [
      { id: "done", status: "complete" as const },
      { id: "running", status: "in progress" as const }
    ];

    expect(settledSyncs(pending, jobs).map((item) => item.jobId)).toEqual(["done", "missing"]);
    // Before the server's list arrived, a job it lacks may still be queued.
    expect(settledSyncs(pending, jobs, false).map((item) => item.jobId)).toEqual(["done"]);
  });

  it("hands an item over to its progress once the worker reports on it", () => {
    const pending = [
      { jobId: "j1", knowledgeId: "a" },
      { jobId: "j2", knowledgeId: "b" }
    ];

    expect(reportedSyncs(pending, { b: {} })).toEqual([{ jobId: "j2", knowledgeId: "b" }]);
  });
});
