/**
 * Settings of the chat partner that are saved while the user chats (the
 * personal assistant's model and reasoning effort, picked in the composer).
 * The backend resolves them from the stored assistant when a question
 * arrives, so a question sent right after a switch must wait for that write
 * to land (the Svelte app's awaitDefaultAssistantUpdates).
 */

const inFlight = new Set<Promise<unknown>>();

/** Registers a save; returns the same promise for the caller's own handling. */
export function trackPartnerUpdate<T>(update: Promise<T>): Promise<T> {
  inFlight.add(update);
  update.finally(() => inFlight.delete(update)).catch(() => {});
  return update;
}

export function hasPendingPartnerUpdates(): boolean {
  return inFlight.size > 0;
}

/** Resolves once every save in flight has settled (failed saves included). */
export async function awaitPartnerUpdates(): Promise<void> {
  while (inFlight.size > 0) await Promise.allSettled([...inFlight]);
}
