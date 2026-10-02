import { describe, expect, it } from "vitest";
import { diffJobs, EMPTY_LEDGER, rememberActiveJob } from "./job-transitions";
import type { Job } from "./jobs";

const job = (id: string, status: Job["status"], extra: Partial<Job> = {}): Job =>
  ({ id, name: id, task: "upload_info_blob", status, ...extra }) as Job;

describe("diffJobs", () => {
  it("reports a job that was active and now has an outcome", () => {
    const first = diffJobs(EMPTY_LEDGER, [job("a", "in progress")]);
    expect(first.transitions).toEqual([]);

    const second = diffJobs(first.ledger, [job("a", "complete")]);
    expect(second.transitions).toEqual([{ job: job("a", "complete"), outcome: "completed" }]);
    expect(second.vanished).toEqual([]);
  });

  it("does not report a job it only ever saw finished", () => {
    const diff = diffJobs(EMPTY_LEDGER, [job("old", "complete")]);
    expect(diff.transitions).toEqual([]);
  });

  it("reports a seeded job whose first polled snapshot is already finished", () => {
    // The upload call returned the job; by the first poll the worker had
    // processed the file. Without the seed this completion was invisible.
    const seeded = rememberActiveJob(EMPTY_LEDGER, job("fast", "complete"));
    const diff = diffJobs(seeded, [job("fast", "complete")]);
    expect(diff.transitions).toEqual([{ job: job("fast", "complete"), outcome: "completed" }]);
  });

  it("keeps a seeded job through polls that do not list it yet", () => {
    const seeded = rememberActiveJob(EMPTY_LEDGER, job("late", "queued"));
    const empty = diffJobs(seeded, []);
    // Not listed yet: nothing vanished, the seed waits for the listing.
    expect(empty.vanished).toEqual([]);
    expect(empty.transitions).toEqual([]);

    const listed = diffJobs(empty.ledger, [job("late", "complete")]);
    expect(listed.transitions).toEqual([{ job: job("late", "complete"), outcome: "completed" }]);
  });

  it("reports an active job that disappeared without an outcome", () => {
    const first = diffJobs(EMPTY_LEDGER, [job("gone", "queued"), job("stay", "complete")]);
    const second = diffJobs(first.ledger, [job("stay", "complete")]);
    expect(second.transitions).toEqual([]);
    expect(second.vanished.map((item) => item.id)).toEqual(["gone"]);
  });

  it("seeds a job a poll listed as finished before the client's call returned", () => {
    // The poll ran between the server finishing the job and the upload
    // promise resolving: the ledger knows the job only as finished. Seeding
    // it makes the outcome news once, as the user expects.
    const first = diffJobs(EMPTY_LEDGER, [job("a", "complete")]);
    expect(first.transitions).toEqual([]);
    const seeded = rememberActiveJob(first.ledger, job("a", "complete"));
    const diff = diffJobs(seeded, [job("a", "complete")]);
    expect(diff.transitions).toEqual([{ job: job("a", "complete"), outcome: "completed" }]);
  });

  it("never reports the same outcome twice", () => {
    const first = diffJobs(EMPTY_LEDGER, [job("a", "in progress")]);
    const second = diffJobs(first.ledger, [job("a", "complete")]);
    expect(second.transitions).toHaveLength(1);
    // Reported: a later seed or poll changes nothing.
    expect(rememberActiveJob(second.ledger, job("a", "complete"))).toBe(second.ledger);
    expect(diffJobs(second.ledger, [job("a", "complete")]).transitions).toEqual([]);
  });

  it("leaves an active job alone when seeded again", () => {
    const first = diffJobs(EMPTY_LEDGER, [job("a", "in progress")]);
    expect(rememberActiveJob(first.ledger, job("a", "in progress"))).toBe(first.ledger);
  });
});
