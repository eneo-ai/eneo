import type { Widget, WidgetTemplate, WidgetTemplateUpdate, WidgetUpdate } from "@eneo/eneo-js";

export type AutosaveStatus = "idle" | "saving" | "saved" | "error";

/**
 * Debounced autosave for a settings form.
 *
 * Edits are applied to `widget` immediately (so the preview and the form stay
 * responsive) and coalesced into one PATCH after a short pause. Nested groups
 * (`texts`, `theme`, `limits`, `privacy`) are sent whole, because the API
 * replaces them as units. A failed save keeps the pending changes so the
 * editor can retry; the server's answer is always the source of truth.
 */
export class Autosave<Resource extends object, Update extends object> {
  widget = $state<Resource>() as Resource;
  status = $state<AutosaveStatus>("idle");
  error = $state<unknown>(null);

  #save: (update: Update) => Promise<Resource>;
  #delay: number;
  #pending: Update = {} as Update;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #inflight: Promise<void> | null = null;
  #dirtyWhileSaving = false;

  constructor(
    widget: Resource,
    save: (update: Update) => Promise<Resource>,
    options: { delay?: number } = {}
  ) {
    this.widget = widget;
    this.#save = save;
    this.#delay = options.delay ?? 600;
  }

  get hasPending(): boolean {
    return Object.keys(this.#pending).length > 0;
  }

  /** Merge a change into the widget and schedule a save. */
  patch(update: Update): void {
    this.widget = { ...this.widget, ...(update as Partial<Resource>) };
    this.#pending = { ...this.#pending, ...update };
    if (this.#inflight) {
      this.#dirtyWhileSaving = true;
      return;
    }
    this.#schedule();
  }

  /** Replace the widget with a server response from another action (activate, pause…). */
  replace(widget: Resource): void {
    if (this.hasPending) {
      // Keep the editor's unsaved values on top of the new lifecycle state.
      this.widget = { ...widget, ...(this.#pending as Partial<Resource>) };
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
    this.#pending = {} as Update;
    this.status = "saving";
    this.error = null;
    try {
      const saved = await this.#save(update);
      // Newer edits win over what the server echoes back for the same keys.
      this.widget = { ...saved, ...(this.#pending as Partial<Resource>) };
      this.status = "saved";
    } catch (error) {
      this.#pending = { ...update, ...this.#pending };
      this.error = error;
      this.status = "error";
    }
  }
}

export class WidgetAutosave extends Autosave<Widget, WidgetUpdate> {}

export class WidgetTemplateAutosave extends Autosave<WidgetTemplate, WidgetTemplateUpdate> {}
