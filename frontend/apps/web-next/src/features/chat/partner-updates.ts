/**
 * The personal chat's assistant Skills and conversation model changes share
 * a queue: each change is checked against the previous choice, and a question
 * waits for both. Conversation settings saves also carry their own revision.
 */

let queue: Promise<unknown> = Promise.resolve();
let pending = 0;

/** Runs a save after every save queued before it; returns its own result. */
export function queuePartnerUpdate<T>(run: () => Promise<T>): Promise<T> {
  const update = queue.then(run, run);
  pending += 1;
  queue = update.catch(() => {}).finally(() => (pending -= 1));
  return update;
}

export function hasPendingPartnerUpdates(): boolean {
  return pending > 0;
}

/** Resolves once every queued save has settled (failed saves included). */
export async function awaitPartnerUpdates(): Promise<void> {
  while (pending > 0) await queue;
}
