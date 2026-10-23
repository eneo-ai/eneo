import type { IntegrationSyncProgress } from "./syncProgress";

const ACTIVE_INTERVAL_MS = 2_000;
const IDLE_INTERVAL_MS = 15_000;

type Options = {
  load: () => Promise<{ items: IntegrationSyncProgress[] }>;
  /** Called when an item that was syncing stops reporting, so counts can be refreshed. */
  onSettled?: (finishedIds: string[]) => void;
};

/**
 * Polls the space's live sync progress: quickly while something syncs or a queued
 * sync waits for a worker, slowly otherwise. Stops for good when the backend does
 * not offer the endpoint or refuses the space.
 */
export class SyncProgressTracker {
  byId = $state<Record<string, IntegrationSyncProgress>>({});
  /** Items whose sync was queued from here; polled for fast until the worker reports on them. */
  pending = $state<readonly string[]>([]);
  /** The pending items the worker has not reported on yet. */
  // eslint-disable-next-line svelte/prefer-svelte-reactivity -- rebuilt on every change, never mutated
  queued: ReadonlySet<string> = $derived(new Set(this.pending.filter((id) => !(id in this.byId))));

  #load: Options["load"];
  #onSettled: Options["onSettled"];
  #timer: ReturnType<typeof setTimeout> | undefined;
  #running = false;
  #unavailable = false;
  #generation = 0;

  constructor({ load, onSettled }: Options) {
    this.#load = load;
    this.#onSettled = onSettled;
  }

  get active(): boolean {
    return Object.keys(this.byId).length > 0;
  }

  start() {
    if (this.#running || this.#unavailable) return;
    this.#running = true;
    void this.#tick();
  }

  stop() {
    this.#running = false;
    this.#generation += 1;
    clearTimeout(this.#timer);
  }

  /** Poll now, e.g. right after the user started a sync. */
  refresh() {
    if (!this.#running) return;
    clearTimeout(this.#timer);
    void this.#tick();
  }

  async #tick() {
    const generation = ++this.#generation;
    try {
      const { items } = await this.#load();
      if (generation !== this.#generation) return;
      const next: Record<string, IntegrationSyncProgress> = {};
      for (const item of items) next[item.integration_knowledge_id] = item;
      const finished = Object.keys(this.byId).filter((id) => !(id in next));
      // Every reader re-renders on a new object; keep the old one when nothing moved.
      if (JSON.stringify(next) !== JSON.stringify(this.byId)) this.byId = next;
      if (finished.length > 0) this.#onSettled?.(finished);
    } catch (error) {
      if (generation !== this.#generation) return;
      const status = (error as { status?: number })?.status;
      // No endpoint (an older backend), or no access to the space any more: asking again won't help.
      if (status === 404 || status === 403 || status === 401) {
        this.#unavailable = true;
        this.stop();
        return;
      }
      console.warn("Could not load the sync progress", error);
    }
    if (!this.#running) return;
    this.#timer = setTimeout(
      () => void this.#tick(),
      this.active || this.queued.size > 0 ? ACTIVE_INTERVAL_MS : IDLE_INTERVAL_MS
    );
  }
}
