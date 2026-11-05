import { beforeNavigate, goto } from "$app/navigation";
import type { BeforeNavigate } from "@sveltejs/kit";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { guardAutosaveNavigation } from "./guardAutosaveNavigation";
import { Autosave } from "./widgetAutosave.svelte";

vi.mock("$app/navigation", () => ({ beforeNavigate: vi.fn(), goto: vi.fn(async () => {}) }));
vi.mock("$lib/paraglide/messages", () => ({
  m: { widget_admin_unsaved_leave_confirm: () => "Leave?" }
}));

function attemptNavigation(callback: (navigation: BeforeNavigate) => void) {
  const cancel = vi.fn();
  callback({
    type: "goto",
    from: null,
    to: {
      url: new URL("https://example.test/next"),
      route: { id: null },
      params: null,
      scroll: null
    },
    willUnload: false,
    complete: Promise.resolve(),
    cancel
  } as BeforeNavigate);
  return cancel;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("widget autosave navigation", () => {
  it("waits for a pending save before replaying navigation", async () => {
    let finishSave!: (value: { name: string }) => void;
    const save = vi.fn(() => new Promise<{ name: string }>((resolve) => (finishSave = resolve)));
    const autosave = new Autosave({ name: "old" }, save);
    autosave.patch({ name: "new" });
    guardAutosaveNavigation(autosave);
    const callback = vi.mocked(beforeNavigate).mock.lastCall![0];

    expect(attemptNavigation(callback)).toHaveBeenCalledOnce();
    expect(save).toHaveBeenCalledOnce();
    expect(goto).not.toHaveBeenCalled();

    finishSave({ name: "new" });
    await vi.waitFor(() => expect(goto).toHaveBeenCalledWith("https://example.test/next"));
    expect(autosave.unsaved).toBe(false);
  });

  it("keeps the editor open when the save fails", async () => {
    const autosave = new Autosave({ name: "old" }, async () => {
      throw new Error("offline");
    });
    autosave.patch({ name: "new" });
    guardAutosaveNavigation(autosave);

    const callback = vi.mocked(beforeNavigate).mock.lastCall![0];
    expect(attemptNavigation(callback)).toHaveBeenCalledOnce();
    await vi.waitFor(() => expect(autosave.status).toBe("error"));
    expect(goto).not.toHaveBeenCalled();
    expect(autosave.widget.name).toBe("new");
  });
});
