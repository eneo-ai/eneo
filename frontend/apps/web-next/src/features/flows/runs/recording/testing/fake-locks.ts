import type { JournalLocks } from "../recording-journal";

type Callback = (lock: { name: string } | null) => unknown;

/**
 * Exclusive Web Locks as the journal and recovery use them: a lock is held
 * while its callback's promise is pending, a second request waits for it,
 * and `ifAvailable` gets null instead of waiting. `holdElsewhere` plays
 * another tab holding a lock.
 */
export function fakeLocks() {
  const held = new Map<string, Promise<unknown>>();
  const elsewhere = new Set<string>();

  async function request(
    name: string,
    optionsOrCallback: { ifAvailable?: boolean } | Callback,
    maybeCallback?: Callback
  ): Promise<unknown> {
    const options = typeof optionsOrCallback === "function" ? {} : optionsOrCallback;
    const callback = (
      typeof optionsOrCallback === "function" ? optionsOrCallback : maybeCallback
    ) as Callback;
    if (options.ifAvailable && (held.has(name) || elsewhere.has(name))) return callback(null);
    while (held.has(name)) await held.get(name)!.catch(() => undefined);
    const run = Promise.resolve().then(() => callback({ name }));
    held.set(name, run);
    try {
      return await run;
    } finally {
      if (held.get(name) === run) held.delete(name);
    }
  }

  return {
    locks: { request } as unknown as JournalLocks,
    isHeld: (name: string) => held.has(name),
    holdElsewhere: (name: string) => elsewhere.add(name),
    releaseElsewhere: (name: string) => elsewhere.delete(name)
  };
}
