import type { JournalLocks } from "../recording-journal";

type Callback = (lock: { name: string } | null) => unknown;

/**
 * Exclusive Web Locks as the keeper, the journal and recovery use them: a
 * lock is held while its callback's promise is pending, a second request
 * waits for it, and `ifAvailable` gets null instead of waiting.
 * `holdElsewhere` plays another tab holding a lock, `deferGrants` a browser
 * that answers later, and `failRequests` one whose requests throw.
 */
export function fakeLocks() {
  const held = new Map<string, Promise<unknown>>();
  const elsewhere = new Map<string, { gone: Promise<void>; release: () => void }>();
  let gate: Promise<void> | null = null;
  let failing: string | null = null;

  const taken = (name: string) => held.get(name) ?? elsewhere.get(name)?.gone;

  async function request(
    name: string,
    optionsOrCallback: { ifAvailable?: boolean } | Callback,
    maybeCallback?: Callback
  ): Promise<unknown> {
    const options = typeof optionsOrCallback === "function" ? {} : optionsOrCallback;
    const callback = (
      typeof optionsOrCallback === "function" ? optionsOrCallback : maybeCallback
    ) as Callback;
    if (failing !== null && name.startsWith(failing)) {
      throw new DOMException("refused", "AbortError");
    }
    if (gate) await gate;
    if (options.ifAvailable && taken(name)) return callback(null);
    while (taken(name)) await taken(name)!.catch(() => undefined);
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
    heldNames: () => [...held.keys()],
    holdElsewhere: (name: string) => {
      let release = () => {};
      const gone = new Promise<void>((resolve) => {
        release = resolve;
      });
      elsewhere.set(name, { gone, release });
    },
    releaseElsewhere: (name: string) => {
      elsewhere.get(name)?.release();
      elsewhere.delete(name);
    },
    /** Requests from now on are answered only once the returned function is called. */
    deferGrants: () => {
      let grant = () => {};
      gate = new Promise<void>((resolve) => {
        grant = () => {
          gate = null;
          resolve();
        };
      });
      return grant;
    },
    /** Requests for names starting with `prefix` throw; null lets them through again. */
    failRequests: (prefix: string | null) => {
      failing = prefix;
    }
  };
}
