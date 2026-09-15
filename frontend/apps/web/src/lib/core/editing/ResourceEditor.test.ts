import type { Eneo } from "@eneo/eneo-js";
import { get } from "svelte/store";
import { describe, expect, test, vi } from "vitest";
import { createResourceEditor } from "./ResourceEditor";

const toastError = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/errors", () => ({ toastError }));

type TestResource = {
  id: string;
  name: string;
};

describe("createResourceEditor save result", () => {
  test("keeps a failed draft retryable and returns true only after persistence succeeds", async () => {
    const saveError = new Error("Persistence failed");
    const updateResource = vi
      .fn<(resource: { id: string }, changes: Partial<TestResource>) => Promise<TestResource>>()
      .mockRejectedValueOnce(saveError)
      .mockImplementation(async (resource, changes) => ({
        id: resource.id,
        name: changes.name ?? "Original name"
      }));
    const editor = createResourceEditor({
      resource: { id: "resource-1", name: "Original name" },
      defaults: {},
      editableFields: { name: true },
      updateResource,
      manageAttachements: false,
      eneo: { files: { delete: vi.fn() } } as unknown as Eneo
    });

    editor.state.update.update((resource) => ({ ...resource, name: "Edited name" }));

    const failedSave = editor.saveChanges();
    expect(get(editor.state.isSaving)).toBe(true);
    await expect(failedSave).resolves.toEqual({ saved: false, error: saveError, handled: false });

    expect(toastError).toHaveBeenCalledWith(saveError);
    expect(get(editor.state.isSaving)).toBe(false);
    expect(get(editor.state.resource).name).toBe("Original name");
    expect(get(editor.state.update).name).toBe("Edited name");
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(true);

    const retriedSave = editor.saveChanges();
    expect(get(editor.state.isSaving)).toBe(true);
    await expect(retriedSave).resolves.toEqual({ saved: true });

    expect(updateResource).toHaveBeenCalledTimes(2);
    expect(get(editor.state.isSaving)).toBe(false);
    expect(get(editor.state.resource).name).toBe("Edited name");
    expect(get(editor.state.update).name).toBe("Edited name");
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(false);
  });

  test("runs saves one at a time and sends what is still unsaved after the first", async () => {
    // Two overlapping PATCHes carry overlapping state and the later one is
    // fenced on a revision the earlier one already advanced. The second
    // request must wait and then carry only what the first did not.
    let resolveFirst!: (value: TestResource) => void;
    const updateResource = vi
      .fn<(resource: { id: string }, changes: Partial<TestResource>) => Promise<TestResource>>()
      .mockImplementationOnce(
        () =>
          new Promise<TestResource>((resolve) => {
            resolveFirst = resolve;
          })
      )
      .mockImplementation(async (resource, changes) => ({ id: resource.id, name: changes.name! }));
    const editor = createResourceEditor({
      resource: { id: "resource-1", name: "Original name" },
      defaults: {},
      editableFields: { name: true },
      updateResource,
      manageAttachements: false,
      eneo: { files: { delete: vi.fn() } } as unknown as Eneo
    });

    editor.state.update.update((resource) => ({ ...resource, name: "First" }));
    const first = editor.saveChanges();
    // The request is sent on the next microtask; the edit below lands while
    // it is in flight, not inside it.
    await Promise.resolve();
    editor.state.update.update((resource) => ({ ...resource, name: "Second" }));
    const second = editor.saveChanges();
    await Promise.resolve();

    expect(updateResource).toHaveBeenCalledTimes(1);
    expect(get(editor.state.isSaving)).toBe(true);

    resolveFirst({ id: "resource-1", name: "First" });
    await expect(first).resolves.toEqual({ saved: true });
    await expect(second).resolves.toEqual({ saved: true });

    expect(updateResource).toHaveBeenCalledTimes(2);
    expect(updateResource.mock.calls[1][1]).toEqual({ name: "Second" });
    expect(get(editor.state.isSaving)).toBe(false);
    expect(get(editor.state.resource).name).toBe("Second");
    expect(get(editor.state.update).name).toBe("Second");
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(false);
  });

  test("keeps an edit made while a save was in flight instead of replacing it with the response", async () => {
    // The response describes the snapshot that was sent; a field the user
    // changed meanwhile is newer than the response and stays unsaved.
    type Doc = { id: string; name: string; description: string };
    let resolveSave!: (value: Doc) => void;
    const updateResource = vi.fn<(resource: { id: string }, changes: Partial<Doc>) => Promise<Doc>>(
      () =>
        new Promise<Doc>((resolve) => {
          resolveSave = resolve;
        })
    );
    const editor = createResourceEditor({
      resource: { id: "doc-1", name: "Original", description: "Original description" },
      defaults: {},
      editableFields: { name: true, description: true },
      updateResource,
      manageAttachements: false,
      eneo: { files: { delete: vi.fn() } } as unknown as Eneo
    });

    editor.state.update.update((doc) => ({ ...doc, name: "Renamed" }));
    const save = editor.saveChanges();
    await Promise.resolve();
    editor.state.update.update((doc) => ({ ...doc, description: "Typed during the save" }));

    resolveSave({ id: "doc-1", name: "Renamed (server)", description: "Original description" });
    await expect(save).resolves.toEqual({ saved: true });

    expect(get(editor.state.update)).toEqual({
      id: "doc-1",
      name: "Renamed (server)",
      description: "Typed during the save"
    });
    expect(get(editor.state.resource).description).toBe("Original description");
    expect(get(editor.state.currentChanges).diff).toEqual({
      description: "Typed during the save"
    });
  });

  test("lets the owner fold server-assigned identities into a field edited during the save", async () => {
    type Item = { id?: string; label: string };
    type Doc = { id: string; items: Item[] };
    let resolveSave!: (value: Doc) => void;
    const updateResource = vi.fn<(resource: { id: string }, changes: Partial<Doc>) => Promise<Doc>>(
      () =>
        new Promise<Doc>((resolve) => {
          resolveSave = resolve;
        })
    );
    const editor = createResourceEditor({
      resource: { id: "doc-1", items: [] as Item[] },
      defaults: {},
      editableFields: { items: ["id", "label"] },
      updateResource,
      manageAttachements: false,
      mergeUnsavedField: (field, local, saved) => {
        if (field !== "items") return local;
        return (local as Item[]).map((item) =>
          item.id
            ? item
            : { ...item, id: (saved as Item[]).find((s) => s.label === item.label)?.id }
        );
      },
      eneo: { files: { delete: vi.fn() } } as unknown as Eneo
    });

    editor.state.update.update((doc) => ({ ...doc, items: [{ label: "a" }] }));
    const save = editor.saveChanges();
    await Promise.resolve();
    editor.state.update.update((doc) => ({ ...doc, items: [...doc.items, { label: "b" }] }));

    resolveSave({ id: "doc-1", items: [{ id: "item-a", label: "a" }] });
    await expect(save).resolves.toEqual({ saved: true });

    expect(get(editor.state.update).items).toEqual([{ id: "item-a", label: "a" }, { label: "b" }]);
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(true);
  });
});
