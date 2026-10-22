/**
 * Starts a recording again by itself after the microphone was lost (it went
 * away, stopped delivering audio, or the recorder failed), where the
 * browser allows a start without a click: a few tries with growing pauses,
 * within half a minute. What was recorded is kept either way; recording
 * again continues the same recording.
 *
 * Read it from React with `useSyncExternalStore(subscribe, getSnapshot)`.
 */

export const RESTART_DELAYS_MS = [1_000, 2_000, 4_000] as const;
/** No try starts later than this after the loss. */
export const RESTART_WITHIN_MS = 30_000;

/**
 * "started": recording again; "refused": nothing to try (no file slot or
 * time left, parts waiting for upload, the microphone refused), so trying
 * stops; "failed": the microphone did not answer this time.
 */
export type RestartOutcome = "started" | "refused" | "failed";

export type RestartSnapshot =
  { phase: "idle" } | { phase: "waiting"; attempt: number } | { phase: "failed" };

const IDLE: RestartSnapshot = { phase: "idle" };

export class AutoRestart {
  #snapshot: RestartSnapshot = IDLE;
  #listeners = new Set<() => void>();
  #try: () => Promise<RestartOutcome> = () => Promise.resolve("refused");
  #onStarted: () => void = () => undefined;
  #now: () => number;
  #timer: ReturnType<typeof setTimeout> | undefined;
  #attempts = 0;
  #since = 0;
  /** Bumped on every cancel, so a try that resolves late changes nothing. */
  #generation = 0;

  constructor(now: () => number = () => performance.now()) {
    this.#now = now;
  }

  /** How a try starts recording, and who hears that it did; read when a try runs. */
  setHandlers({
    attempt,
    onStarted
  }: {
    attempt: () => Promise<RestartOutcome>;
    onStarted: () => void;
  }): void {
    this.#try = attempt;
    this.#onStarted = onStarted;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  getSnapshot = (): RestartSnapshot => this.#snapshot;

  /** The recording stopped by itself: it is tried again after a pause. */
  lost(): void {
    if (this.#snapshot.phase === "waiting") return;
    this.#attempts = 0;
    this.#since = this.#now();
    this.#schedule();
  }

  /** The person took over (recorded, discarded, closed): no more tries. */
  cancel(): void {
    this.#generation += 1;
    clearTimeout(this.#timer);
    this.#timer = undefined;
    this.#set(IDLE);
  }

  #schedule() {
    const delay = RESTART_DELAYS_MS[this.#attempts];
    if (delay === undefined || this.#now() + delay - this.#since > RESTART_WITHIN_MS) {
      this.#set({ phase: "failed" });
      return;
    }
    const generation = this.#generation;
    this.#set({ phase: "waiting", attempt: this.#attempts + 1 });
    this.#timer = setTimeout(() => {
      this.#timer = undefined;
      this.#attempts += 1;
      void this.#try()
        .catch((): RestartOutcome => "failed")
        .then((outcome) => {
          if (generation !== this.#generation) return;
          if (outcome === "started") {
            this.#set(IDLE);
            this.#onStarted();
          } else if (outcome === "refused") {
            this.#set(IDLE);
          } else {
            this.#schedule();
          }
        });
    }, delay);
  }

  #set(next: RestartSnapshot) {
    if (next === this.#snapshot) return;
    this.#snapshot = next;
    for (const listener of this.#listeners) listener();
  }
}
