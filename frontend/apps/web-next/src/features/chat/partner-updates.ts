/**
 * Settings of the chat partner that are saved while the user chats (the
 * personal assistant's model, reasoning effort and own Skills, picked in the
 * composer). The backend resolves them from the stored assistant when a
 * question arrives, so a question sent right after a switch must wait for
 * that write to land. Saves run one at a time, in the order they were made,
 * so a quick A → B → C never lets an older write land last (the Svelte app's
 * updateDefaultAssistant chain).
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
