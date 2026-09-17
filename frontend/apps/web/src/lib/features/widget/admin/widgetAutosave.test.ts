/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import type { Widget } from "@eneo/eneo-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WidgetAutosave } from "./widgetAutosave.svelte";

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
    allowed_origins: [],
    ...overrides
  } as unknown as Widget;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("WidgetAutosave", () => {
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
    expect(save).toHaveBeenCalledWith({ name: "Ny", texts: { title: "Hej", welcome: "" } });
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
    expect(save).toHaveBeenLastCalledWith({ name: "B" });
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
    expect(save).toHaveBeenLastCalledWith({ name: "A" });
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
