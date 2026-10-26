import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const api = vi.hoisted(() => ({ delete: vi.fn(), upload: vi.fn() }));

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    icons: {
      delete: api.delete,
      upload: api.upload,
      url: ({ id }: { id: string }) => `/icons/${id}/`
    }
  })
}));

import { createIconEditor } from "./createIconEditor.svelte";

function editorFor(
  options: {
    iconId?: string | null;
    savedIconId?: string | null;
    setIconId?: (id: string | null) => unknown;
  } = {}
) {
  const calls: string[] = [];
  let iconId = options.iconId === undefined ? "icon-1" : options.iconId;
  api.delete.mockReset();
  api.delete.mockImplementation(async ({ id }: { id: string }) => {
    calls.push(`delete ${id}`);
  });
  api.upload.mockReset();
  api.upload.mockResolvedValue({ id: "upload-2" });
  const editor = createIconEditor({
    iconId: () => iconId,
    setIconId:
      options.setIconId ??
      (async (id) => {
        calls.push(`set ${id}`);
        iconId = id;
      }),
    savedIconId: options.savedIconId === undefined ? undefined : () => options.savedIconId
  });
  return { editor, calls };
}

describe("createIconEditor", () => {
  // The server deletes the icon a persisted change replaced.
  it.each([
    ["removing", (editor: ReturnType<typeof createIconEditor>) => editor.remove(), "set null"],
    [
      "replacing",
      (editor: ReturnType<typeof createIconEditor>) => editor.upload(new File(["x"], "icon.png")),
      "set upload-2"
    ]
  ])("leaves a persisted icon to the server when %s it", async (_, change, set) => {
    const { editor, calls } = editorFor();

    await change(editor);

    expect(calls).toEqual([set]);
    expect(editor.error).toBeNull();
  });

  it.each([
    ["removed", "upload-1", "saved-1", ["set null", "delete upload-1"]],
    ["removed", "saved-1", "saved-1", ["set null"]],
    ["replaced", "upload-1", "saved-1", ["set upload-2", "delete upload-1"]],
    ["replaced", "saved-1", "saved-1", ["set upload-2"]]
  ])(
    "deletes a staged icon %s before saving only if it was never saved (%s, saved %s)",
    async (action, iconId, savedIconId, expected) => {
      const { editor, calls } = editorFor({ iconId, savedIconId });

      if (action === "removed") await editor.remove();
      else await editor.upload(new File(["x"], "icon.png"));

      expect(calls).toEqual(expected);
    }
  );

  it("ignores a refused delete of a staged upload", async () => {
    const { editor } = editorFor({ iconId: "upload-1", savedIconId: "saved-1" });
    api.delete.mockImplementationOnce(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
      throw new Error("The icon is in use.");
    });

    await editor.remove();

    expect(editor.url).toBeNull();
    expect(editor.error).toBeNull();
  });

  it("keeps the icon and deletes nothing when it cannot be cleared", async () => {
    const { editor } = editorFor({
      iconId: "upload-1",
      savedIconId: "saved-1",
      setIconId: async () => {
        throw new Error("offline");
      }
    });

    await editor.remove();

    expect(api.delete).not.toHaveBeenCalled();
    expect(editor.url).toBe("/icons/upload-1/");
    expect(editor.error).toBe(m.avatar_delete_failed());
  });
});
