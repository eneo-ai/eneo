import type { Widget, WidgetUpdate } from "@eneo/eneo-js";

export type AutosaveStatus = "idle" | "saving" | "saved" | "error";

type Save = (update: WidgetUpdate) => Promise<Widget>;

/**
 * Debounced autosave for the widget settings form.
 *
 * Edits are applied to `widget` immediately (so the preview and the form stay
 * responsive) and coalesced into one PATCH after a short pause. Nested groups
 * (`texts`, `theme`, `limits`, `privacy`) are sent whole, because the API
 * replaces them as units. A failed save keeps the pending changes so the
 * editor can retry; the server's answer is always the source of truth.
 */
export class WidgetAutosave {
  widget = $state<Widget>() as Widget;
  status = $state<AutosaveStatus>("idle");
  error = $state<unknown>(null);

  #save: Save;
  #delay: number;
  #pending: WidgetUpdate = {};
  #timer: ReturnType<typeof setTimeout> | null = null;
  #inflight: Promise<void> | null = null;
  #dirtyWhileSaving = false;

  constructor(widget: Widget, save: Save, options: { delay?: number } = {}) {
    this.widget = widget;
    this.#save = save;
    this.#delay = options.delay ?? 600;
  }

  get hasPending(): boolean {
    return Object.keys(this.#pending).length > 0;
  }

  /** Merge a change into the widget and schedule a save. */
  patch(update: WidgetUpdate): void {
    this.widget = { ...this.widget, ...(update as Partial<Widget>) };
    this.#pending = { ...this.#pending, ...update };
    if (this.#inflight) {
      this.#dirtyWhileSaving = true;
      return;
    }
    this.#schedule();
  }

  /** Replace the widget with a server response from another action (activate, pause…). */
  replace(widget: Widget): void {
    if (this.hasPending) {
      // Keep the editor's unsaved values on top of the new lifecycle state.
      this.widget = { ...widget, ...(this.#pending as Partial<Widget>) };
    } else {
      this.widget = widget;
    }
  }

  /** Save now; resolves when nothing is pending or the save has failed. */
  async flush(): Promise<void> {
    if (this.#timer) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }
    if (this.#inflight) {
      await this.#inflight;
    }
    if (!this.hasPending) return;
    this.#inflight = this.#run().finally(() => {
      this.#inflight = null;
    });
    await this.#inflight;
    if (this.#dirtyWhileSaving) {
      this.#dirtyWhileSaving = false;
      await this.flush();
    }
  }

  retry(): Promise<void> {
    return this.flush();
  }

  #schedule(): void {
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = setTimeout(() => {
      this.#timer = null;
      void this.flush();
    }, this.#delay);
  }

  async #run(): Promise<void> {
    const update = this.#pending;
    this.#pending = {};
    this.status = "saving";
    this.error = null;
    try {
      const saved = await this.#save(update);
      // Newer edits win over what the server echoes back for the same keys.
      this.widget = { ...saved, ...(this.#pending as Partial<Widget>) };
      this.status = "saved";
    } catch (error) {
      this.#pending = { ...update, ...this.#pending };
      this.error = error;
      this.status = "error";
    }
  }
}
