import { get } from "svelte/store";
import { beforeEach, describe, expect, it } from "vitest";
import {
  MISSING_JOB_GRACE_MS,
  pendingSyncs,
  reportedSyncs,
  settledSyncs,
  trackSyncs,
  untrackSyncs
} from "./pendingSyncs";

describe("pendingSyncs", () => {
  beforeEach(() => pendingSyncs.set([]));

  it("waits for an item's newest job only, stamped with when it was queued", () => {
    trackSyncs(
      [
        { jobId: "j1", knowledgeId: "a" },
        { jobId: "j2", knowledgeId: "b" }
      ],
      1_000
    );
    trackSyncs([{ jobId: "j3", knowledgeId: "a" }], 2_000);

    expect(get(pendingSyncs)).toEqual([
      { jobId: "j2", knowledgeId: "b", queuedAt: 1_000 },
      { jobId: "j3", knowledgeId: "a", queuedAt: 2_000 }
    ]);

    untrackSyncs(["j2"]);
    expect(get(pendingSyncs)).toEqual([{ jobId: "j3", knowledgeId: "a", queuedAt: 2_000 }]);
  });

  it("counts a job as settled once it is over, or gone from a list asked for after it", () => {
    const queuedAt = 1_000;
    const pending = [
      { jobId: "done", knowledgeId: "a", queuedAt },
      { jobId: "running", knowledgeId: "b", queuedAt },
      { jobId: "missing", knowledgeId: "c", queuedAt }
    ];
    const jobs = [
      { id: "done", status: "complete" as const },
      { id: "running", status: "in progress" as const }
    ];
    const later = queuedAt + MISSING_JOB_GRACE_MS;

    expect(settledSyncs(pending, jobs, true, later).map((item) => item.jobId)).toEqual([
      "done",
      "missing"
    ]);
    // Before the server's list arrived, a job it lacks may still be queued.
    expect(settledSyncs(pending, jobs, false, later).map((item) => item.jobId)).toEqual(["done"]);
    // A list sent before the job was added lacks it too; that is no proof it ended.
    expect(settledSyncs(pending, jobs, true, later - 1).map((item) => item.jobId)).toEqual([
      "done"
    ]);
  });

  it("hands an item over to its progress once the worker reports on its sync", () => {
    const pending = [
      { jobId: "j1", knowledgeId: "a" },
      { jobId: "j2", knowledgeId: "b" },
      { jobId: "j3", knowledgeId: "c" }
    ];

    expect(reportedSyncs(pending, { b: {}, c: { sync_type: "delta" } })).toEqual([
      { jobId: "j2", knowledgeId: "b" }
    ]);
  });
});
