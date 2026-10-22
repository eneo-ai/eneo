import type { CorrectionSet } from "./transcript-corrections";

/**
 * A reviewer's corrections of one transcript as a local draft: each change
 * applies at once and the draft saves itself a moment later, as one request
 * with the whole set, fenced by the revision the last save returned (the
 * draft never takes over someone else's newer set while it holds changes of
 * its own). A failed save keeps the draft and stops saving until it is
 * retried; changes made meanwhile stay in the draft. `flush` sends what
 * waits at once and settles once nothing does: a review approves only after
 * it, and leaving the page sends what waits.
 *
 * Read it from React with `useSyncExternalStore(subscribe, getSnapshot)`.
 */

/** Saved; a change waits for its save; a save is on its way; a save failed. */
export type DraftStatus = "saved" | "waiting" | "saving" | "failed";

export type DraftState = {
  set: CorrectionSet;
  /** The revision the draft's changes are fenced by. */
  revision: number | null;
  status: DraftStatus;
  /** Why the last save failed, while the status says so. */
  problem: unknown;
};

/** How long after a change the draft saves itself. */
export const AUTOSAVE_DELAY_MS = 1_000;

/** Saves a set over `revision` and answers the revision it got. */
export type SaveDraft = (set: CorrectionSet, revision: number | null) => Promise<number | null>;

export class CorrectionsDraft {
  #state: DraftState;
  #listeners = new Set<() => void>();
  #save: SaveDraft;
  #delayMs: number;
  #timer: ReturnType<typeof setTimeout> | undefined;
  #inFlight: Promise<void> | null = null;
  /** The draft changed while a save was on its way: it saves again after. */
  #changedSince = false;
  /** Bumped by a discard: a save on its way then answers nobody. */
  #generation = 0;

  constructor(
    set: CorrectionSet,
    revision: number | null,
    save: SaveDraft,
    delayMs = AUTOSAVE_DELAY_MS
  ) {
    this.#state = { set, revision, status: "saved", problem: null };
    this.#save = save;
    this.#delayMs = delayMs;
  }

  /** Who saves the draft from now on (the latest render's request). */
  setSave(save: SaveDraft): void {
    this.#save = save;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  getSnapshot = (): DraftState => this.#state;

  /** A change: it applies at once and saves itself shortly after, unless a save failed. */
  change(set: CorrectionSet): void {
    const { status } = this.#state;
    if (this.#inFlight) {
      this.#changedSince = true;
      this.#update({ set });
      return;
    }
    this.#update({ set, status: status === "failed" ? "failed" : "waiting" });
    if (status !== "failed") this.#schedule();
  }

  /** What the server holds now, taken over only while the draft holds no changes of its own. */
  sync(set: CorrectionSet, revision: number | null): void {
    if (this.#state.status !== "saved" || this.#inFlight) return;
    if (revision === this.#state.revision) return;
    this.#update({ set, revision });
  }

  /** Throws the draft's unsaved changes away for what the server holds. */
  discard(set: CorrectionSet, revision: number | null): void {
    clearTimeout(this.#timer);
    this.#generation += 1;
    this.#changedSince = false;
    this.#update({ set, revision, status: "saved", problem: null });
  }

  /** Sends what waits at once; resolves true once everything is saved. */
  async flush(): Promise<boolean> {
    clearTimeout(this.#timer);
    for (;;) {
      if (this.#inFlight) {
        await this.#inFlight;
        continue;
      }
      if (this.#state.status === "waiting") {
        this.#send();
        continue;
      }
      return this.#state.status === "saved";
    }
  }

  /** Tries a failed save again, with the draft as it is now. */
  retry(): Promise<boolean> {
    if (this.#state.status === "failed") this.#update({ status: "waiting", problem: null });
    return this.flush();
  }

  dispose(): void {
    clearTimeout(this.#timer);
    this.#listeners.clear();
  }

  #schedule() {
    clearTimeout(this.#timer);
    this.#timer = setTimeout(() => void this.flush(), this.#delayMs);
  }

  #send() {
    const { set, revision } = this.#state;
    const generation = this.#generation;
    this.#changedSince = false;
    this.#update({ status: "saving", problem: null });
    this.#inFlight = this.#save(set, revision)
      .then(
        (saved) => {
          if (generation !== this.#generation) return;
          const again = this.#changedSince;
          this.#update({ revision: saved, status: again ? "waiting" : "saved" });
        },
        (error: unknown) => {
          if (generation !== this.#generation) return;
          this.#update({ status: "failed", problem: error });
        }
      )
      .finally(() => {
        this.#inFlight = null;
        if (this.#state.status === "waiting") this.#schedule();
      });
  }

  #update(change: Partial<DraftState>) {
    this.#state = { ...this.#state, ...change };
    for (const listener of this.#listeners) listener();
  }
}
