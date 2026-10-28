/**
 * One identity per browser: when a tab signs in or leaves its session, every
 * other tab reloads under the new session cookie. Otherwise a tab keeps the
 * previous identity's data in memory (the query cache with its user, tenant
 * and settings) and renders it, or writes with it, under the next identity's
 * session. The message carries nothing but its type.
 */
const IDENTITY_CHANGED = "identity-changed";

let channel: BroadcastChannel | undefined;
// One channel per document for both directions: a channel never receives its
// own messages, so the announcing tab does not reload itself.
const identityChannel = () => (channel ??= new BroadcastChannel("eneo-identity"));

/** Call right before this tab continues as a new identity or leaves its session. */
export function announceIdentityChange(): void {
  identityChannel().postMessage(IDENTITY_CHANGED);
}

/** Reloads this tab when another tab announces an identity change. Returns the unsubscribe. */
export function reloadOnIdentityChange(): () => void {
  const reload = (event: MessageEvent) => {
    if (event.data === IDENTITY_CHANGED) window.location.reload();
  };
  identityChannel().addEventListener("message", reload);
  return () => identityChannel().removeEventListener("message", reload);
}
