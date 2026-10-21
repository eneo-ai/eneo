/**
 * @typedef {{
 *   phase: string,
 *   done: number,
 *   total: number | null,
 *   background?: boolean
 * }} SnapshotProgress
 *
 * `background` marks a sync nobody started from the UI (a change notification's
 * delta pass).
 *
 * @typedef {{
 *   state: string,
 *   progress: SnapshotProgress | null,
 *   outcome: string,
 *   failures: string[]
 * }} Snapshot
 *
 * `outcome` is a signature of what the source's rows say about its last sync
 * (times, failing items). `failures` names each failing part with its latest
 * attempt, so a part that was failing already and was not tried again is no
 * news, while one that failed again is.
 *
 * @typedef {{kind: 'started' | 'queued' | 'finished' | 'failed' | 'stopped'}
 *   | {kind: 'progress', done: number, total: number | null}} Transition
 */

/** A running sync's count is spoken at most this often. */
export const PROGRESS_ANNOUNCE_INTERVAL_MS = 10_000;
/** How long the end of a sync waits for the source's rows to tell how it ended. */
export const OUTCOME_WAIT_MS = 30_000;

const FINISHING = "finishing";

/**
 * Decides, snapshot by snapshot, what one source's sync means for a screen
 * reader. The first snapshot is not news. A sync's end is spoken once the
 * source's rows record its outcome, never from the vanished progress alone,
 * which proves neither success nor final counts; if no record arrives in time
 * the end is spoken without an outcome.
 *
 * Syncs nobody started from the UI stay quiet unless `speakBackground`; with
 * `onlyStartedHere` only a sync this page saw queued is spoken (a list of many
 * sources), and `speakProgress: false` leaves counts out.
 */
export class SyncAnnouncer {
  /** @type {Snapshot | null} */
  #previous = null;
  #progressAt = 0;
  #startedHere = false;
  /**
   * The failing parts when this sync was queued or started. Rows re-read while
   * it runs already carry its new attempt time, so they cannot tell a part that
   * failed again from one that was failing before.
   * @type {string[] | null}
   */
  #baseline = null;
  /** @type {{outcome: string, failures: string[], at: number, speak: boolean} | null} */
  #awaiting = null;

  /**
   * @param {{speakProgress?: boolean, speakBackground?: boolean, onlyStartedHere?: boolean}} [options]
   */
  constructor({ speakProgress = true, speakBackground = false, onlyStartedHere = false } = {}) {
    this.speakProgress = speakProgress;
    this.speakBackground = speakBackground;
    this.onlyStartedHere = onlyStartedHere;
  }

  /**
   * When an ended sync stops waiting for its outcome, so a caller whose
   * snapshots stop changing can call `next` again then; null when not waiting.
   * @returns {number | null}
   */
  get awaitingUntil() {
    return this.#awaiting ? this.#awaiting.at + OUTCOME_WAIT_MS : null;
  }

  /**
   * @param {Snapshot} next
   * @param {number} now
   * @returns {Transition | null}
   */
  next(next, now) {
    const previous = this.#previous;
    this.#previous = next;
    if (!previous) return null;
    if (next.state === "queued") {
      this.#startedHere = true;
      this.#baseline ??= previous.failures;
    }

    const was = previous.progress;
    const current = next.progress;
    const speak = this.#speaks(was ?? current);

    if (current && !was) {
      this.#baseline ??= previous.failures;
      this.#awaiting = null;
      this.#progressAt = now;
      return speak ? { kind: "started" } : null;
    }
    // A sync ended: its progress went away, or a queued sync ended before any
    // progress was read (a small folder, or one that failed at once).
    const ended =
      !current && (was !== null || (previous.state === "queued" && next.state !== "queued"));
    if (ended) {
      this.#awaiting = {
        outcome: previous.outcome,
        failures: this.#baseline ?? previous.failures,
        at: now,
        speak
      };
    }
    if (this.#awaiting && !current) {
      const awaiting = this.#awaiting;
      if (next.outcome !== awaiting.outcome) {
        this.#settle();
        if (!awaiting.speak) return null;
        const failedNow = next.failures.some((failure) => !awaiting.failures.includes(failure));
        return { kind: failedNow ? "failed" : "finished" };
      }
      if (now - awaiting.at >= OUTCOME_WAIT_MS) {
        this.#settle();
        return awaiting.speak ? { kind: "stopped" } : null;
      }
      if (ended) return null;
    }

    if (current && was) {
      if (!speak || !this.speakProgress) return null;
      const reachedFinishing = current.phase === FINISHING && was.phase !== FINISHING;
      const advanced =
        current.done > was.done && now - this.#progressAt >= PROGRESS_ANNOUNCE_INTERVAL_MS;
      if (!reachedFinishing && !advanced) return null;
      this.#progressAt = now;
      return { kind: "progress", done: current.done, total: current.total };
    }
    if (next.state === "queued" && previous.state !== "queued") {
      return { kind: "queued" };
    }
    return null;
  }

  #settle() {
    this.#awaiting = null;
    this.#startedHere = false;
    this.#baseline = null;
  }

  /** @param {SnapshotProgress | null} progress */
  #speaks(progress) {
    if (this.onlyStartedHere) return this.#startedHere;
    return this.#startedHere || this.speakBackground || !progress?.background;
  }
}

/** @param {number | null} previous @param {number | null} next */
export function problemCountChanged(previous, next) {
  return previous !== null && next !== null && previous !== next;
}
