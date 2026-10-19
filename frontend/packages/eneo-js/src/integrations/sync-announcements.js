/** @typedef {{state: string, progress: {phase: string, done: number, total: number | null} | null}} Snapshot */
/** @typedef {{kind: 'started' | 'stopped' | 'queued'} | {kind: 'progress', done: number, total: number | null}} Transition */

export const PROGRESS_ANNOUNCE_INTERVAL_MS = 10_000;

/**
 * A progress snapshot is advisory, never evidence of success or final counts.
 * Both frontends translate these transitions through their own message system.
 * @param {Snapshot | null} previous
 * @param {Snapshot} next
 * @param {number} sinceProgressAnnounced
 * @param {{speakProgress?: boolean}} [options]
 * @returns {Transition | null}
 */
export function syncAnnouncement(
  previous,
  next,
  sinceProgressAnnounced,
  { speakProgress = true } = {}
) {
  if (!previous) return null;
  const was = previous.progress;
  const now = next.progress;
  if (now && !was) return { kind: "started" };
  if (!now && was) return { kind: "stopped" };
  if (now && was) {
    if (!speakProgress) return null;
    if (
      now.phase === was.phase &&
      (now.done === was.done || sinceProgressAnnounced < PROGRESS_ANNOUNCE_INTERVAL_MS)
    )
      return null;
    return { kind: "progress", done: now.done, total: now.total };
  }
  if (next.state === "queued" && previous.state !== "queued") return { kind: "queued" };
  return null;
}

/** @param {number | null} previous @param {number | null} next */
export function problemCountChanged(previous, next) {
  return previous !== null && next !== null && previous !== next;
}
