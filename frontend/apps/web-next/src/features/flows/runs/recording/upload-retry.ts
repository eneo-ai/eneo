/**
 * Automatic retries of a recorded part whose upload failed for a reason that
 * passes (the network, a timeout, a busy server): it exists nowhere else, so
 * it is sent again by itself, after growing waits. The browser coming back
 * online brings the next attempt forward; that counts as the attempt. After
 * the last wait no timer sends it, but the browser coming back online still
 * does, and its waits then start over as after "Försök igen": an outage
 * longer than the waits does not leave it behind. A refusal that does not
 * pass (too large, not accepted) is never scheduled.
 */

/** The waits before each automatic attempt. */
export const UPLOAD_RETRY_DELAYS_MS = [5_000, 15_000, 30_000, 60_000, 120_000] as const;

type Timers = {
  setTimeout: (callback: () => void, ms: number) => ReturnType<typeof setTimeout>;
  clearTimeout: (timer: ReturnType<typeof setTimeout>) => void;
  now: () => number;
};

const browserTimers: Timers = {
  setTimeout: (callback, ms) => setTimeout(callback, ms),
  clearTimeout: (timer) => clearTimeout(timer),
  now: () => Date.now()
};

export class UploadRetries {
  #send: (key: string) => void;
  #timers: Timers;
  #pending = new Map<string, ReturnType<typeof setTimeout>>();
  #attempts = new Map<string, number>();
  /** Parts whose automatic attempts are spent, which the browser coming back online sends. */
  #spent = new Set<string>();

  /** `send` sends the part with entry key `key` again. */
  constructor(send: (key: string) => void, timers: Timers = browserTimers) {
    this.#send = send;
    this.#timers = timers;
  }

  /**
   * A part's upload failed for a reason that passes: when it goes again by
   * itself (epoch ms), or null when no automatic attempt is left.
   */
  failed(key: string): number | null {
    this.#clear(key);
    const delay = UPLOAD_RETRY_DELAYS_MS[this.#attempts.get(key) ?? 0];
    if (delay === undefined) {
      this.#spent.add(key);
      return null;
    }
    this.#pending.set(
      key,
      this.#timers.setTimeout(() => this.#attempt(key), delay)
    );
    return this.#timers.now() + delay;
  }

  /**
   * The browser is back online: every part waiting for its next attempt goes
   * now, and so does every part whose attempts were spent, with its waits
   * starting over.
   */
  online(): void {
    for (const key of [...this.#pending.keys()]) {
      this.#clear(key);
      this.#attempt(key);
    }
    for (const key of [...this.#spent]) {
      this.reset(key);
      this.#send(key);
    }
  }

  /** A person sent the part, it uploaded, or it left the form: its waits start over. */
  reset(key: string): void {
    this.#clear(key);
    this.#attempts.delete(key);
    this.#spent.delete(key);
  }

  dispose(): void {
    for (const key of [...this.#pending.keys()]) this.#clear(key);
    this.#attempts.clear();
    this.#spent.clear();
  }

  #attempt(key: string) {
    this.#pending.delete(key);
    this.#attempts.set(key, (this.#attempts.get(key) ?? 0) + 1);
    this.#send(key);
  }

  #clear(key: string) {
    const timer = this.#pending.get(key);
    if (timer !== undefined) this.#timers.clearTimeout(timer);
    this.#pending.delete(key);
  }
}
