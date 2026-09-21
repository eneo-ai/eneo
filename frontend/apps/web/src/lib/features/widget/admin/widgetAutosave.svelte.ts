import type { Widget, WidgetTemplate, WidgetTemplateUpdate, WidgetUpdate } from "@eneo/eneo-js";
import { isStaleEditorError } from "./errors";

export type AutosaveStatus = "idle" | "saving" | "saved" | "error" | "conflict";

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

  #save: (update: Update, baseline: Resource) => Promise<Resource>;
  #baseline: Resource;
  #replacement = 0;
  #delay: number;
  #pending: Update = {} as Update;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #inflight: Promise<void> | null = null;
  #dirtyWhileSaving = false;

  constructor(
    widget: Resource,
    save: (update: Update, baseline: Resource) => Promise<Resource>,
    options: { delay?: number } = {}
  ) {
    this.widget = widget;
    this.#baseline = widget;
    this.#save = save;
    this.#delay = options.delay ?? 600;
  }

  get hasPending(): boolean {
    return Object.keys(this.#pending).length > 0;
  }

  /** Something would be lost if the page went away right now. */
  get unsaved(): boolean {
    return this.hasPending || this.status === "saving";
  }

  /** Merge a change into the widget and schedule a save. */
  patch(update: Update): void {
    this.widget = { ...this.widget, ...(update as Partial<Resource>) };
    this.#pending = { ...this.#pending, ...update };
    if (this.status === "conflict") return;
    if (this.#inflight) {
      this.#dirtyWhileSaving = true;
      return;
    }
    this.#schedule();
  }

  /** Replace the widget with a server response from another action (activate, pause…). */
  replace(widget: Resource): void {
    this.#baseline = widget;
    this.#replacement += 1;
    if (this.hasPending) {
      // Keep the editor's unsaved values on top of the new lifecycle state.
      this.widget = { ...widget, ...(this.#pending as Partial<Resource>) };
    } else {
      this.widget = widget;
    }
  }

  /** Explicitly discard a conflicted draft after the editor reloads it. */
  reload(widget: Resource): void {
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = null;
    this.#pending = {} as Update;
    this.#dirtyWhileSaving = false;
    this.replace(widget);
    this.error = null;
    this.status = "idle";
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
    if (!this.hasPending || this.status === "conflict") return;
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
    const replacement = this.#replacement;
    const update = this.#pending;
    this.#pending = {} as Update;
    this.status = "saving";
    this.error = null;
    try {
      const saved = await this.#save(update, this.#baseline);
      // Newer edits win over what the server echoes back for the same keys.
      if (replacement === this.#replacement) {
        this.#baseline = saved;
        this.widget = { ...saved, ...(this.#pending as Partial<Resource>) };
      }
      this.status = "saved";
    } catch (error) {
      this.#pending = { ...update, ...this.#pending };
      this.error = error;
      // A conflict (or a lock published underneath the editor) means this
      // copy is stale: automatic saves stop until the editor reloads.
      this.status = isStaleEditorError(error) ? "conflict" : "error";
    }
  }
}

export class WidgetAutosave extends Autosave<Widget, Omit<WidgetUpdate, "revision">> {
  constructor(
    widget: Widget,
    save: (update: WidgetUpdate) => Promise<Widget>,
    options: { delay?: number } = {}
  ) {
    super(widget, (update, baseline) => save({ ...update, revision: baseline.revision }), options);
  }
}

export class WidgetTemplateAutosave extends Autosave<WidgetTemplate, WidgetTemplateUpdate> {}
