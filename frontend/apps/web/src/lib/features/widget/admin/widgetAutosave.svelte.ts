import type { Widget, WidgetTemplate, WidgetTemplateUpdate, WidgetUpdate } from "@eneo/eneo-js";
import { untrack } from "svelte";
import { isStaleEditorError, widgetFieldErrors } from "./errors";

export type AutosaveStatus = "idle" | "saving" | "saved" | "error" | "conflict" | "refused";

type Options = {
  delay?: number;
  /**
   * The fields a failed save is pinned to, as `group` or `group.field` paths
   * with a message each. A refused group is held back instead of resent, so
   * one bad value never blocks every later edit.
   */
  fieldErrors?: (error: unknown) => Record<string, string>;
};

const group = (path: string) => path.split(".")[0];

/**
 * Debounced autosave for a settings form.
 *
 * Edits are applied to `widget` immediately (so the preview and the form stay
 * responsive) and coalesced into one PATCH after a short pause. Nested groups
 * (`texts`, `theme`, `limits`, `privacy`) are sent whole, because the API
 * replaces them as units. A failed save keeps the pending changes so the
 * editor can retry; the server's answer is always the source of truth.
 *
 * A group the server refuses because of its own value stays on screen with
 * its message in `refusals` but is not sent again until it is edited; the
 * rest of the edits keep saving.
 */
export class Autosave<Resource extends object, Update extends object> {
  widget = $state<Resource>() as Resource;
  status = $state<AutosaveStatus>("idle");
  error = $state<unknown>(null);
  /** Field paths the server refused, each with the message to show at the field. */
  refusals = $state<Record<string, string>>({});
  /** Edits a field keeps to itself because they cannot be sent as they are. */
  #drafts = $state<Record<string, true>>({});

  #save: (update: Update, baseline: Resource) => Promise<Resource>;
  #fieldErrors: (error: unknown) => Record<string, string>;
  #baseline: Resource;
  #replacement = 0;
  #delay: number;
  #pending: Update = {} as Update;
  #refused: Update = {} as Update;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #inflight: Promise<void> | null = null;
  #dirtyWhileSaving = false;
  #exclusiveTail: Promise<void> = Promise.resolve();

  constructor(
    widget: Resource,
    save: (update: Update, baseline: Resource) => Promise<Resource>,
    options: Options = {}
  ) {
    this.widget = widget;
    this.#baseline = widget;
    this.#save = save;
    this.#delay = options.delay ?? 600;
    this.#fieldErrors = options.fieldErrors ?? (() => ({}));
  }

  get hasPending(): boolean {
    return Object.keys(this.#pending).length > 0;
  }

  /** Edits the server refused; shown, but not sent until they are changed. */
  get hasRefused(): boolean {
    return Object.keys(this.#refused).length > 0;
  }

  get hasDrafts(): boolean {
    return Object.keys(this.#drafts).length > 0;
  }

  /** Something would be lost if the page went away right now. */
  get unsaved(): boolean {
    return this.hasPending || this.hasRefused || this.hasDrafts || this.status === "saving";
  }

  /** Edits that saving on the way out cannot rescue, so leaving should ask first. */
  get stranded(): boolean {
    if (this.hasRefused || this.hasDrafts) return true;
    return (this.status === "error" || this.status === "conflict") && this.hasPending;
  }

  /**
   * Register an edit a field holds back because it cannot be sent yet (an
   * invalid line, a repeated question), so leaving the page asks before it is
   * lost. Safe to call from an effect.
   */
  markDraft(key: string, held: boolean): void {
    untrack(() => {
      if (held === key in this.#drafts) return;
      if (held) {
        this.#drafts = { ...this.#drafts, [key]: true };
      } else {
        const { [key]: _released, ...rest } = this.#drafts;
        this.#drafts = rest;
      }
    });
  }

  /** Merge a change into the widget and schedule a save. */
  patch(update: Update): void {
    this.#release(Object.keys(update));
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
    // Keep the editor's unsaved values on top of the new lifecycle state.
    this.widget = this.#onTop(widget);
  }

  /**
   * Run another action on the resource (publish, pause, link a template…)
   * with no save overlapping it: pending edits are saved first, and edits
   * made meanwhile wait for the result, whose revision the server moves to,
   * instead of carrying the one before it. The action returns the new
   * resource, or null to leave the baseline alone (the editor moved on).
   */
  exclusive(action: () => Promise<Resource | null>): Promise<void> {
    // One action at a time, its flush included: two actions waiting on the
    // same save would otherwise both start from the revision it returns.
    const run = this.#exclusiveTail.then(() => this.#runExclusive(action));
    this.#exclusiveTail = run.then(
      () => undefined,
      () => undefined
    );
    return run;
  }

  async #runExclusive(action: () => Promise<Resource | null>): Promise<void> {
    await this.flush();
    const held = action().then((result) => {
      if (result !== null) this.replace(result);
    });
    this.#inflight = held
      .then(
        () => undefined,
        () => undefined
      )
      .finally(() => {
        this.#inflight = null;
      });
    try {
      await held;
    } finally {
      this.#dirtyWhileSaving = false;
      if (this.hasPending) void this.flush();
    }
  }

  /** Drop refused edits of these groups (all by default), e.g. before an action that overwrites them. */
  discardRefused(keys: string[] = Object.keys(this.#refused)): void {
    this.#release(keys);
    this.widget = this.#onTop(this.#baseline);
    if (this.status === "refused" && !this.hasRefused) this.status = "idle";
  }

  /** Explicitly discard a conflicted draft after the editor reloads it. */
  reload(widget: Resource): void {
    this.#drafts = {};
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = null;
    this.#pending = {} as Update;
    this.#refused = {} as Update;
    this.refusals = {};
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
    // A refusal re-saves the rest from inside the save that owns the flush;
    // every caller waits for that save too before it looks at what is pending.
    while (this.#inflight) {
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

  #onTop(base: Resource): Resource {
    return {
      ...base,
      ...(this.#refused as Partial<Resource>),
      ...(this.#pending as Partial<Resource>)
    };
  }

  #release(keys: string[]): void {
    if (keys.some((key) => key in this.#refused)) {
      const refused = { ...this.#refused } as Record<string, unknown>;
      for (const key of keys) delete refused[key];
      this.#refused = refused as Update;
    }
    this.#keepRefusals((path) => !keys.includes(group(path)));
  }

  #keepRefusals(keep: (path: string) => boolean): void {
    const paths = Object.keys(this.refusals);
    if (paths.every(keep)) return;
    this.refusals = Object.fromEntries(
      Object.entries(this.refusals).filter(([path]) => keep(path))
    );
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
      // A save from before a reload belongs to the resource that was shown
      // then: neither its answer nor its failure may touch the current one.
      if (replacement !== this.#replacement) return;
      // Newer edits win over what the server echoes back for the same keys.
      this.#baseline = saved;
      this.widget = this.#onTop(saved);
      // The server accepted the whole resource, so only refusals of values
      // still held back remain true.
      this.#keepRefusals((path) => group(path) in this.#refused);
      this.status = this.hasRefused ? "refused" : "saved";
    } catch (error) {
      if (replacement !== this.#replacement) return;
      this.error = error;
      if (isStaleEditorError(error)) {
        this.#pending = { ...update, ...this.#pending };
        // A conflict (or a lock published underneath the editor) means this
        // copy is stale: automatic saves stop until the editor reloads.
        this.status = "conflict";
        return;
      }
      // An edit made while this save was in flight replaces the refused
      // value and gets its own attempt.
      const fields = Object.entries(this.#fieldErrors(error)).filter(
        ([path]) => !(group(path) in this.#pending)
      );
      const refusedKeys = Object.keys(update).filter((key) =>
        fields.some(([path]) => group(path) === key)
      );
      const kept = { ...update } as Record<string, unknown>;
      const refused = { ...this.#refused } as Record<string, unknown>;
      for (const key of refusedKeys) {
        refused[key] = kept[key];
        delete kept[key];
      }
      this.#refused = refused as Update;
      this.#pending = { ...(kept as Update), ...this.#pending };
      this.refusals = { ...this.refusals, ...Object.fromEntries(fields) };
      if (refusedKeys.length === 0) {
        this.status = "error";
        return;
      }
      this.status = "refused";
      // What the server did not object to is saved without the refused group.
      if (this.hasPending) this.#dirtyWhileSaving = true;
    }
  }
}

export class WidgetAutosave extends Autosave<Widget, Omit<WidgetUpdate, "revision">> {
  constructor(
    widget: Widget,
    save: (update: WidgetUpdate) => Promise<Widget>,
    options: { delay?: number } = {}
  ) {
    super(widget, (update, baseline) => save({ ...update, revision: baseline.revision }), {
      ...options,
      fieldErrors: widgetFieldErrors
    });
  }
}

export class WidgetTemplateAutosave extends Autosave<WidgetTemplate, WidgetTemplateUpdate> {
  constructor(
    template: WidgetTemplate,
    save: (update: WidgetTemplateUpdate) => Promise<WidgetTemplate>,
    options: { delay?: number } = {}
  ) {
    super(template, save, { ...options, fieldErrors: widgetFieldErrors });
  }
}
