/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { EneoError, type Widget, type WidgetPolicy, type WidgetPolicyUpdate } from "@eneo/eneo-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Autosave, WidgetAutosave } from "./widgetAutosave.svelte";

function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: "w1",
    name: "Chatt",
    texts: { title: "", welcome: "" },
    theme: { primary_color: "#1F4E79", radius: 12 },
    limits: { daily_token_budget: 1000 },
    privacy: { retention_days: 30 },
    status: "draft",
    token_generation: 0,
    show_sources: true,
    show_tool_activity: true,
    revision: 0,
    allowed_origins: [],
    ...overrides
  } as unknown as Widget;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("WidgetAutosave", () => {
  it("sends the last saved revision on each update", async () => {
    const save = vi.fn(async (update) => widget({ ...update, revision: update.revision + 1 }));
    const autosave = new WidgetAutosave(widget({ revision: 4 }), save);
    autosave.patch({ name: "First" });
    await autosave.flush();
    autosave.patch({ name: "Second" });
    await autosave.flush();
    expect(save).toHaveBeenNthCalledWith(1, { name: "First", revision: 4 });
    expect(save).toHaveBeenNthCalledWith(2, { name: "Second", revision: 5 });
  });

  it("stops automatic saves on a conflict until the user reloads", async () => {
    let reject!: (reason: Error) => void;
    const save = vi.fn(
      () =>
        new Promise<Widget>((_, rejectSave) => {
          reject = rejectSave;
        })
    );
    const autosave = new WidgetAutosave(widget(), save, { delay: 10 });
    autosave.patch({ name: "A" });
    const flushing = autosave.flush();
    autosave.patch({ name: "B" });
    reject(new EneoError("Conflict", "RESPONSE", 409, 0));
    await flushing;
    await autosave.retry();
    autosave.patch({ name: "C" });
    await vi.runAllTimersAsync();
    expect(save).toHaveBeenCalledTimes(1);
    expect(autosave.status).toBe("conflict");
    expect(autosave.widget.name).toBe("C");
    expect(autosave.hasPending).toBe(true);
    autosave.reload(widget({ revision: 3, status: "paused" }));
    expect(autosave.status).toBe("idle");
    expect(autosave.hasPending).toBe(false);
    expect(autosave.widget.revision).toBe(3);
  });

  it("does not replace a newer pause response with an older save response", async () => {
    let resolve!: (value: Widget) => void;
    const autosave = new WidgetAutosave(
      widget({ status: "active" }),
      () =>
        new Promise<Widget>((resolveSave) => {
          resolve = resolveSave;
        })
    );
    autosave.patch({ name: "Changed" });
    const flushing = autosave.flush();
    autosave.replace(widget({ status: "paused", revision: 2, token_generation: 1 }));
    resolve(widget({ status: "active", revision: 1 }));
    await flushing;
    expect(autosave.widget.status).toBe("paused");
    expect(autosave.widget.token_generation).toBe(1);
    expect(autosave.widget.revision).toBe(2);
  });
  it("applies edits immediately and coalesces them into one save", async () => {
    const save = vi.fn(async (update) => widget({ ...update, token_generation: 1 }));
    const autosave = new WidgetAutosave(widget(), save, { delay: 100 });

    autosave.patch({ name: "Ny" });
    autosave.patch({ texts: { title: "Hej", welcome: "" } });
    expect(autosave.widget.name).toBe("Ny");
    expect(autosave.widget.texts.title).toBe("Hej");
    expect(save).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(100);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith({
      revision: 0,
      name: "Ny",
      texts: { title: "Hej", welcome: "" }
    });
    expect(autosave.status).toBe("saved");
    expect(autosave.widget.token_generation).toBe(1);
    expect(autosave.hasPending).toBe(false);
  });

  it("saves edits made during an in-flight save afterwards", async () => {
    let resolveFirst!: (value: Widget) => void;
    const save = vi
      .fn()
      .mockImplementationOnce(() => new Promise<Widget>((resolve) => (resolveFirst = resolve)))
      .mockImplementationOnce(async (update: Partial<Widget>) => widget(update));
    const autosave = new WidgetAutosave(widget(), save, { delay: 10 });

    autosave.patch({ name: "A" });
    await vi.advanceTimersByTimeAsync(10);
    expect(autosave.status).toBe("saving");
    autosave.patch({ name: "B" });
    resolveFirst(widget({ name: "A" }));
    await vi.advanceTimersByTimeAsync(0);
    await vi.runAllTimersAsync();

    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith({ revision: 0, name: "B" });
    expect(autosave.widget.name).toBe("B");
  });

  it("keeps pending changes on failure so they can be retried", async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockImplementationOnce(async (update: Partial<Widget>) => widget(update));
    const autosave = new WidgetAutosave(widget(), save, { delay: 10 });

    autosave.patch({ name: "A" });
    await vi.advanceTimersByTimeAsync(10);
    expect(autosave.status).toBe("error");
    expect(autosave.hasPending).toBe(true);

    await autosave.retry();
    expect(save).toHaveBeenLastCalledWith({ revision: 0, name: "A" });
    expect(autosave.status).toBe("saved");
    expect(autosave.hasPending).toBe(false);
  });

  it("keeps unsaved edits when the widget is replaced by a lifecycle action", () => {
    const autosave = new WidgetAutosave(widget(), vi.fn(), { delay: 1000 });
    autosave.patch({ name: "Utkast" });
    autosave.replace(widget({ status: "active" }));
    expect(autosave.widget.status).toBe("active");
    expect(autosave.widget.name).toBe("Utkast");
  });
});

describe("policy autosave", () => {
  const policy: WidgetPolicy = {
    max_daily_token_budget: 1000,
    min_retention_days: 0,
    max_retention_days: 365,
    allow_bot_protection_none: false
  };

  it("serialises saves and keeps an edit made while the first save is in flight", async () => {
    let resolveFirst!: (value: WidgetPolicy) => void;
    const save = vi
      .fn<(update: WidgetPolicyUpdate) => Promise<WidgetPolicy>>()
      .mockImplementationOnce(() => new Promise((resolve) => (resolveFirst = resolve)))
      .mockImplementationOnce(async () => ({
        ...policy,
        max_daily_token_budget: 2000,
        min_retention_days: 5
      }));
    const autosave = new Autosave<WidgetPolicy, WidgetPolicyUpdate>(policy, save, { delay: 10 });

    autosave.patch({ max_daily_token_budget: 2000 });
    await vi.advanceTimersByTimeAsync(10);
    expect(save).toHaveBeenCalledTimes(1);
    expect(autosave.status).toBe("saving");

    // Edited while the first response is outstanding: shown at once, sent later.
    autosave.patch({ min_retention_days: 5 });
    expect(autosave.widget.min_retention_days).toBe(5);
    expect(save).toHaveBeenCalledTimes(1);

    // The server echoes the whole policy as of the first patch only.
    resolveFirst({ ...policy, max_daily_token_budget: 2000 });
    await vi.advanceTimersByTimeAsync(0);
    expect(autosave.widget.min_retention_days).toBe(5);

    await vi.runAllTimersAsync();
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith({ min_retention_days: 5 }, expect.anything());
    expect(autosave.widget).toMatchObject({ max_daily_token_budget: 2000, min_retention_days: 5 });
    expect(autosave.status).toBe("saved");
    expect(autosave.hasPending).toBe(false);
  });
});
