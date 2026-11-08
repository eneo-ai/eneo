import { isJobActive, jobOutcome, type Job, type JobOutcome } from "./jobs";

/**
 * What JobsProvider knows about each job, keyed by job id: the job as last
 * seen, and whether the client seeded it before any poll listed it. A job the
 * client started (the job an upload call returns) is seeded as active, so its
 * first polled snapshot counts as a transition even when that snapshot
 * already says "complete". Without the seed, a job that finished between the
 * call and the first poll was never seen as active and the data it produced
 * was never refreshed.
 *
 * The list keeps a completed job for five minutes: one that finished while
 * the feed was down for longer leaves the list unseen. A job the ledger knows
 * as running that a list misses (for a seeded job, a list begun after it was
 * registered) stays in the ledger, as still running, while JobsProvider reads
 * it by id, so its outcome is reported like any other.
 */
export type LedgerEntry = {
  job: Job;
  /** Registered by the client before any poll listed it. */
  seeded: boolean;
  /**
   * For a seeded job: how many lists had started when it was registered. Only
   * a list started after that can say it is gone (`diffJobs`' `listedBy`).
   */
  seededAfter?: number;
  /** Its outcome has been reported (toast, refresh); never report it twice. */
  reported: boolean;
  /** Left the list while running and is being read by id: not over yet. */
  reading?: boolean;
};
export type JobLedger = ReadonlyMap<string, LedgerEntry>;

export type JobTransition = { job: Job; outcome: JobOutcome };

export type JobDiff = {
  /** Jobs that were active (or seeded) and now report an outcome. */
  transitions: JobTransition[];
  /**
   * Active jobs that disappeared from the list before reporting an outcome.
   * Each stays in the ledger, marked as being read, until the caller reads
   * it by id and lists what it found or settles it (`settleRead`).
   */
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
export function rememberActiveJob(ledger: JobLedger, job: Job, listsStarted = 0): JobLedger {
  const existing = ledger.get(job.id);
  if (existing && (existing.reported || isJobActive(existing.job))) return ledger;
  const next = new Map(ledger);
  // Treated as active whatever the server said, so the next snapshot decides.
  next.set(job.id, {
    job: { ...job, status: "queued" },
    seeded: true,
    seededAfter: listsStarted,
    reported: false
  });
  return next;
}

/**
 * Whether a job is over by a loaded snapshot and the ledger `diffJobs` made of
 * it: listed with an outcome, or no longer listed at all. Only a list the
 * server sent (`listReceived`) says a job is gone: pushed updates fill the
 * cache before it arrives. A job the client started that no list has shown
 * yet is still to come, and so is one being read by id.
 */
export function isJobOver(
  jobId: string,
  snapshot: readonly Job[],
  ledger: JobLedger,
  listReceived: boolean
): boolean {
  const job = snapshot.find((candidate) => candidate.id === jobId);
  if (job) return !isJobActive(job);
  const entry = ledger.get(jobId);
  return listReceived && entry?.seeded !== true && entry?.reading !== true;
}

/**
 * Compare a polled snapshot with the ledger and report what finished.
 * `listedBy` numbers the list the snapshot rests on, counting lists in the
 * order they started: a job the client started is gone from it only if that
 * list started after the job was registered.
 */
export function diffJobs(ledger: JobLedger, snapshot: readonly Job[], listedBy = 0): JobDiff {
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
    const listPredatesIt = previous.seeded && listedBy <= (previous.seededAfter ?? 0);
    if (listPredatesIt || previous.reading) {
      // The list began before the job did, or the job is being read: wait.
      next.set(id, previous);
    } else if (isJobActive(previous.job)) {
      vanished.push(previous.job);
      next.set(id, { ...previous, reading: true });
    }
  }
  return { transitions, vanished, ledger: next };
}

/**
 * Whether a read by id that began on `lookup` (the job's ledger entry when
 * `diffJobs` found it vanished) still speaks for the job. A list that showed
 * the job since, or missed it again and so began a newer read, replaced the
 * entry: the older read's answer is out of date and is ignored.
 */
export function isCurrentRead(ledger: JobLedger, lookup: LedgerEntry): boolean {
  return lookup.reading === true && ledger.get(lookup.job.id) === lookup;
}

/**
 * End the read by id that began on `lookup`. A job that is `gone` leaves the
 * ledger. Any other is a running job again: the next snapshot that lists it
 * reports its outcome, and one that still misses it has it read again. An
 * out-of-date read (`isCurrentRead`) changes nothing.
 */
export function settleRead(ledger: JobLedger, lookup: LedgerEntry, gone: boolean): JobLedger {
  if (!isCurrentRead(ledger, lookup)) return ledger;
  const next = new Map(ledger);
  if (gone) next.delete(lookup.job.id);
  else next.set(lookup.job.id, { ...lookup, reading: false });
  return next;
}
