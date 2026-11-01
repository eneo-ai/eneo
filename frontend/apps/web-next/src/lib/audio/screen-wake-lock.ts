/**
 * Keeps a phone's screen on while a recording runs: a screen that locks can
 * stop the page's capture. The browser releases the lock whenever the page is
 * hidden (and may at other times), saying so with the lock's "release" event;
 * a new one is taken when the page is visible and the lock still wanted.
 * Without the Screen Wake Lock API nothing happens. Port of the Svelte app's
 * screenWakeLock.ts; the Flows and Apps recorders share it.
 */

type WakeLockLike = Pick<EventTarget, "addEventListener"> & { release(): Promise<void> };
export type WakeLockHost = { request(type: "screen"): Promise<WakeLockLike> };
type PageLike = Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">;

const MAX_REQUESTS_WHILE_VISIBLE = 3;

export function browserWakeLock(): WakeLockHost | undefined {
  return (globalThis.navigator as (Navigator & { wakeLock?: WakeLockHost }) | undefined)?.wakeLock;
}

export class ScreenWakeLock {
  readonly #host: WakeLockHost | undefined;
  /** Without a page (outside a document) the lock is asked for as if it were visible. */
  readonly #page: PageLike | undefined;
  #wanted = false;
  #lock: WakeLockLike | null = null;
  // One request at a time; a call made meanwhile asks again once it settles.
  #requesting: Promise<void> | null = null;
  #askAgain = false;
  // Requests since the page last became visible: a browser that keeps releasing
  // the lock (battery saver) is not asked without end.
  #requestsWhileVisible = 0;

  /**
   * `host` is required: `undefined` means "no wake lock" (a test, a browser
   * without the API), never the browser's own, so callers pass browserWakeLock().
   */
  constructor(host: WakeLockHost | undefined, page: PageLike | undefined = globalThis.document) {
    this.#host = host;
    this.#page = page;
  }

  hold(): void {
    if (this.#wanted) return;
    this.#wanted = true;
    // A new recording gets a fresh allowance.
    this.#requestsWhileVisible = 0;
    this.#page?.addEventListener("visibilitychange", this.#onVisibility);
    void this.#take();
  }

  release(): void {
    if (!this.#wanted) return;
    this.#wanted = false;
    this.#page?.removeEventListener("visibilitychange", this.#onVisibility);
    const lock = this.#lock;
    this.#lock = null;
    void lock?.release().catch(() => undefined);
  }

  #visible(): boolean {
    return !this.#page || this.#page.visibilityState === "visible";
  }

  #onVisibility = () => {
    if (!this.#visible()) return;
    this.#requestsWhileVisible = 0;
    void this.#take();
  };

  #take(): Promise<void> {
    if (this.#requesting) {
      this.#askAgain = true;
      return this.#requesting;
    }
    this.#requesting = this.#request().finally(() => {
      this.#requesting = null;
      if (this.#askAgain) {
        this.#askAgain = false;
        void this.#take();
      }
    });
    return this.#requesting;
  }

  async #request(): Promise<void> {
    if (!this.#host || !this.#wanted || this.#lock || !this.#visible()) return;
    if (this.#requestsWhileVisible >= MAX_REQUESTS_WHILE_VISIBLE) return;
    this.#requestsWhileVisible += 1;
    try {
      const lock = await this.#host.request("screen");
      if (!this.#wanted) {
        void lock.release().catch(() => undefined);
        return;
      }
      this.#lock = lock;
      // Released by the browser (a hidden page, battery saver): forget it, so the
      // next visible page takes a new one.
      lock.addEventListener("release", () => {
        if (this.#lock !== lock) return;
        this.#lock = null;
        // Released while the page is visible and the recording goes on: ask again.
        if (this.#wanted) void this.#take();
      });
    } catch {
      // Refused (battery saver, a hidden page): the recording goes on without it.
    }
  }
}
