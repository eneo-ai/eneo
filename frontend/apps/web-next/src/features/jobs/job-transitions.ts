import { isJobActive, jobOutcome, type Job, type JobOutcome } from "./jobs";

/**
 * What JobsProvider knows about each job, keyed by job id: the job as last
 * seen, and whether the client seeded it before any poll listed it. A job the
 * client started (the job an upload call returns) is seeded as active, so its
 * first polled snapshot counts as a transition even when that snapshot
 * already says "complete". Without the seed, a job that finished between the
 * call and the first poll was never seen as active and the data it produced
 * was never refreshed. A seeded job stays in the ledger until a poll lists
 * it; the jobs endpoint lists finished jobs for a while, so it will.
 */
export type LedgerEntry = {
  job: Job;
  /** Registered by the client before any poll listed it. */
  seeded: boolean;
  /** Its outcome has been reported (toast, refresh); never report it twice. */
  reported: boolean;
};
export type JobLedger = ReadonlyMap<string, LedgerEntry>;

export type JobTransition = { job: Job; outcome: JobOutcome };

export type JobDiff = {
  /** Jobs that were active (or seeded) and now report an outcome. */
  transitions: JobTransition[];
  /** Active jobs that disappeared from the list before reporting an outcome. */
  vanished: Job[];
  ledger: JobLedger;
};

export const EMPTY_LEDGER: JobLedger = new Map();

/**
 * Remember a job the client just started. A job the ledger only knows as
 * finished and unreported (a poll listed it before the client's call came
 * back) is seeded all the same: the client has just learned it owns it, and
 * its outcome is still news. An active or already reported job is left alone.
 */
export function rememberActiveJob(ledger: JobLedger, job: Job): JobLedger {
  const existing = ledger.get(job.id);
  if (existing && (existing.reported || isJobActive(existing.job))) return ledger;
  const next = new Map(ledger);
  // Treated as active whatever the server said, so the next snapshot decides.
  next.set(job.id, { job: { ...job, status: "queued" }, seeded: true, reported: false });
  return next;
}

/** Compare a polled snapshot with the ledger and report what finished. */
export function diffJobs(ledger: JobLedger, snapshot: readonly Job[]): JobDiff {
  const next = new Map<string, LedgerEntry>();
  const transitions: JobTransition[] = [];
  for (const job of snapshot) {
    const previous = ledger.get(job.id);
    const wasActive = previous !== undefined && isJobActive(previous.job);
    const outcome = wasActive ? jobOutcome(job) : null;
    if (outcome !== null) transitions.push({ job, outcome });
    next.set(job.id, {
      job,
      seeded: false,
      reported: outcome !== null || (previous?.reported ?? false)
    });
  }
  const vanished: Job[] = [];
  for (const [id, previous] of ledger) {
    if (next.has(id)) continue;
    if (previous.seeded) {
      // Not listed yet: keep waiting for it.
      next.set(id, previous);
    } else if (isJobActive(previous.job)) {
      vanished.push(previous.job);
    }
  }
  return { transitions, vanished, ledger: next };
}
