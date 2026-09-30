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

  test("keeps an in-place edit made while a save was in flight", async () => {
    // A bound input (`$update.description = …`) mutates the store's object and
    // sets it again; the comparison after the response must not see its own
    // snapshot mutated along with it.
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
    const bound = get(editor.state.update);
    bound.description = "Typed during the save";
    editor.state.update.set(bound);

    resolveSave({ id: "doc-1", name: "Renamed", description: "Original description" });
    await expect(save).resolves.toEqual({ saved: true });

    expect(get(editor.state.update).description).toBe("Typed during the save");
    expect(get(editor.state.currentChanges).diff).toEqual({
      description: "Typed during the save"
    });
  });

  test("defers a queued save that canSave refuses when it runs and keeps the state dirty", async () => {
    let ready = false;
    const updateResource = vi.fn(
      async (resource: { id: string; name: string }, changes: Partial<{ name: string }>) => ({
        ...resource,
        ...changes
      })
    );
    const editor = createResourceEditor({
      resource: { id: "doc-1", name: "Original" },
      defaults: {},
      editableFields: { name: true },
      updateResource,
      manageAttachements: false,
      canSave: () => ready,
      eneo: { files: { delete: vi.fn() } } as unknown as Eneo
    });

    editor.state.update.update((doc) => ({ ...doc, name: "Renamed" }));
    await expect(editor.saveChanges()).resolves.toEqual({ saved: false, deferred: true });
    expect(updateResource).not.toHaveBeenCalled();
    expect(get(editor.state.isSaving)).toBe(false);
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(true);

    ready = true;
    await expect(editor.saveChanges()).resolves.toEqual({ saved: true });
    expect(updateResource).toHaveBeenCalledTimes(1);
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(false);
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

describe("createResourceEditor queued write", () => {
  type Doc = { id: string; name: string; revision: number };
  const makeEditor = (
    updateResource: (resource: Doc, changes: Partial<Doc>) => Promise<Doc> = async (
      resource,
      changes
    ) => ({ ...resource, ...changes, revision: resource.revision + 1 })
  ) =>
    createResourceEditor({
      resource: { id: "doc-1", name: "Original", revision: 1 } as Doc,
      defaults: {},
      editableFields: { name: true },
      updateResource,
      manageAttachements: false,
      eneo: { files: { delete: vi.fn() } } as unknown as Eneo
    });

  test("runs after the saves queued before it, with the state they persisted, and adopts what it returns", async () => {
    let resolveSave!: (value: Doc) => void;
    const editor = makeEditor(
      () =>
        new Promise<Doc>((resolve) => {
          resolveSave = resolve;
        })
    );
    editor.state.update.update((doc) => ({ ...doc, name: "Saved" }));
    const save = editor.saveChanges();
    const write = vi.fn(async (doc: Doc) => ({
      persisted: { revision: doc.revision + 1 },
      result: `written at ${doc.revision}`
    }));

    const queued = editor.queueWrite(write);
    await Promise.resolve();
    expect(write).not.toHaveBeenCalled();

    resolveSave({ id: "doc-1", name: "Saved", revision: 2 });
    await expect(save).resolves.toEqual({ saved: true });
    await expect(queued).resolves.toBe("written at 2");

    expect(get(editor.state.resource).revision).toBe(3);
    expect(get(editor.state.update).revision).toBe(3);
    expect(get(editor.state.isSaving)).toBe(false);
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(false);
  });

  test("keeps unsaved edits when it adopts the persisted fields", async () => {
    const editor = makeEditor();
    editor.state.update.update((doc) => ({ ...doc, name: "Unsaved" }));

    await editor.queueWrite(async () => ({
      persisted: { name: "Server copy", revision: 2 },
      result: undefined
    }));

    expect(get(editor.state.resource)).toEqual({ id: "doc-1", name: "Server copy", revision: 2 });
    expect(get(editor.state.update)).toEqual({ id: "doc-1", name: "Unsaved", revision: 2 });
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(true);
  });

  test("adopts a persisted object as its own copy, so an in-place edit of it is unsaved and saved", async () => {
    type Nested = { id: string; metadata: { name: string } };
    const updateResource = vi.fn(async (resource: Nested, changes: Partial<Nested>) => ({
      ...resource,
      ...changes
    }));
    const editor = createResourceEditor({
      resource: { id: "doc-1", metadata: { name: "Original" } } as Nested,
      defaults: {},
      editableFields: { metadata: true },
      updateResource,
      manageAttachements: false,
      eneo: { files: { delete: vi.fn() } } as unknown as Eneo
    });

    await editor.queueWrite(async () => ({
      persisted: { metadata: { name: "Server" } },
      result: undefined
    }));
    // A bound input (`$update.metadata.name = …`) mutates the object in place.
    const bound = get(editor.state.update);
    bound.metadata.name = "Local edit";
    editor.state.update.set(bound);

    expect(get(editor.state.resource).metadata).toEqual({ name: "Server" });
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(true);
    await expect(editor.saveChanges()).resolves.toEqual({ saved: true });
    expect(updateResource).toHaveBeenCalledTimes(1);
    expect(updateResource.mock.calls[0][1]).toEqual({ metadata: { name: "Local edit" } });
  });

  test("a failed write rejects to its caller, adopts nothing and leaves the queue running", async () => {
    toastError.mockClear();
    const editor = makeEditor();
    const failure = new Error("stale");

    await expect(
      editor.queueWrite(async () => {
        throw failure;
      })
    ).rejects.toBe(failure);

    expect(toastError).not.toHaveBeenCalled();
    expect(get(editor.state.resource).revision).toBe(1);
    editor.state.update.update((doc) => ({ ...doc, name: "Next" }));
    await expect(editor.saveChanges()).resolves.toEqual({ saved: true });
    expect(get(editor.state.resource)).toEqual({ id: "doc-1", name: "Next", revision: 2 });
  });
});
