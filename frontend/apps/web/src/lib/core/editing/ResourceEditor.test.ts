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
    await expect(failedSave).resolves.toBe(false);

    expect(toastError).toHaveBeenCalledWith(saveError);
    expect(get(editor.state.isSaving)).toBe(false);
    expect(get(editor.state.resource).name).toBe("Original name");
    expect(get(editor.state.update).name).toBe("Edited name");
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(true);

    const retriedSave = editor.saveChanges();
    expect(get(editor.state.isSaving)).toBe(true);
    await expect(retriedSave).resolves.toBe(true);

    expect(updateResource).toHaveBeenCalledTimes(2);
    expect(get(editor.state.isSaving)).toBe(false);
    expect(get(editor.state.resource).name).toBe("Edited name");
    expect(get(editor.state.update).name).toBe("Edited name");
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(false);
  });
});

describe("createResourceEditor discarding a staged icon", () => {
  test.each([
    ["an upload replacing the saved icon", "saved-1", "upload-1", undefined, ["upload-1"]],
    ["an upload on a resource without an icon", null, "upload-1", undefined, ["upload-1"]],
    ["only the icon field", "saved-1", "upload-1", "icon_id" as const, ["upload-1"]],
    ["a removal of the saved icon", "saved-1", null, undefined, []],
    ["another field", "saved-1", "upload-1", "name" as const, []]
  ])("deletes what was uploaded for %s", (_, saved, staged, field, deleted) => {
    const deleteIcon = vi.fn<(params: { id: string }) => Promise<void>>(async () => {});
    const editor = createResourceEditor({
      resource: { id: "space-1", name: "Space", icon_id: saved as string | null },
      defaults: {},
      editableFields: { name: true, icon_id: true },
      updateResource: async (resource) => resource,
      manageAttachements: false,
      manageIcon: true,
      eneo: { icons: { delete: deleteIcon } } as unknown as Eneo
    });
    editor.state.update.update((resource) => ({ ...resource, icon_id: staged }));

    editor.discardChanges(field);

    expect(deleteIcon.mock.calls.map(([params]) => params.id)).toEqual(deleted);
  });
});
