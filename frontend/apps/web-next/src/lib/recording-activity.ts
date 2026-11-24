/**
 * Whether a recording runs (or is paused) in this tab, for what the page says
 * outside the recorder: the warning before the sign-in ends tells what happens
 * to it. A recorder holds it while it records and lets go when it stops.
 *
 * Read it from React with `useSyncExternalStore(subscribeRecording, recordingHeld)`.
 */

let holds = 0;
const listeners = new Set<() => void>();

function changed() {
  for (const listener of listeners) listener();
}

/** A recording runs from now on; the returned function lets go, once. */
export function holdRecording(): () => void {
  holds += 1;
  changed();
  let released = false;
  return () => {
    if (released) return;
    released = true;
    holds -= 1;
    changed();
  };
}

export function recordingHeld(): boolean {
  return holds > 0;
}

export function subscribeRecording(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
